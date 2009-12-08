#!/usr/bin/python

#import base64
import datetime
import libxml2
import optparse
import os
import random
import string
import sys

NAGIOSCMDs = [ '/usr/local/nagios/var/rw/nagios.cmd', '/var/lib/nagios3/rw/nagios.cmd', ]
CHECKRESULTDIRs = [ '/usr/local/nagios/var/spool/checkresults', '/var/lib/nagios3/spool/checkresults', ]
MODEs = [ 'passive', 'passive_check', 'checkresult', 'checkresult_check', 'active', ]

parser = optparse.OptionParser()

parser.add_option('-u', '', dest='url', help='URL of status file (xml)')
parser.add_option('-f', '', dest='file', help='(Path and) file name of status file')
parser.add_option('-S', '', dest='schemacheck', help='Check XML against DTD')
parser.add_option('-s', '', dest='seconds', type='int', help='Maximum age in seconds of xml timestamp')
parser.add_option('-m', '', action='store_true', dest='markold', help='Mark (Set state) of too old checks as UNKNOWN')
parser.add_option('-O', '', dest='mode', help='Where/Howto output the results ("%s")' % '", "'.join(MODEs))
parser.add_option('-p', '', dest='pipe', help='Full path to nagios.cmd')
parser.add_option('-r', '', dest='checkresultdir', help='Full path to checkresult directory')
parser.add_option('-H', '', dest='host', help='Hostname to search for in XML file')
parser.add_option('-D', '', dest='service', help='Service description to search for in XML file')
parser.add_option('-v', '', action='count', dest='verb', help='Verbose output')

parser.set_defaults(url=None)
parser.set_defaults(file='nagixsc.xml')
parser.set_defaults(schemacheck='')
parser.set_defaults(seconds=14400)
parser.set_defaults(markold=False)
parser.set_defaults(mode=False)
parser.set_defaults(pipe=None)
parser.set_defaults(checkresultdir=None)
parser.set_defaults(host=None)
parser.set_defaults(service=None)
parser.set_defaults(verb=0)

(options, args) = parser.parse_args()

##############################################################################

from nagixsc import *

##############################################################################

if options.mode not in MODEs:
	print 'Not an allowed mode "%s" - allowed are: %s' % (options.mode, ", ".join(MODEs))
	sys.exit(127)

# Check command line options wrt mode
if options.mode == 'passive' or options.mode == 'passive_check':
	debug(1, options.verb, 'Running in passive mode')
	if options.pipe == None and options.verb <= 2:
		for nagioscmd in NAGIOSCMDs:
			if os.path.exists(nagioscmd):
				options.pipe = nagioscmd

	if options.pipe == None and options.verb <= 2:
		print 'Need full path to the nagios.cmd pipe!'
		sys.exit(127)

	debug(2, options.verb, 'nagios.cmd found at %s' % options.pipe)

elif options.mode == 'checkresult' or options.mode == 'checkresult_check':
	debug(1, options.verb, 'Running in checkresult mode')
	if options.checkresultdir == None and options.verb <= 2:
		for crd in CHECKRESULTDIRs:
			if os.path.exists(crd):
				options.checkresultdir = crd

	if options.checkresultdir == None and options.verb <= 2:
		print 'Need full path to the checkresultdir!'
		sys.exit(127)

	debug(2, options.verb, 'Checkresult dir: %s' % options.checkresultdir)

elif options.mode == 'active':
	debug(1, options.verb, 'Running in active/plugin mode')
	if options.host == None:
		debug(1, options.verb, 'No host specified, using first host in XML file')
	if options.service == None:
		print 'No service specified on command line!'
		sys.exit(127)

##############################################################################

now = int(datetime.datetime.now().strftime('%s'))

# Get URL or file
if options.url != None:
	import urllib2

	response = urllib2.urlopen(options.url)
	doc = libxml2.parseDoc(response.read())
	response.close()
else:
	doc = libxml2.parseFile(options.file)


# Check XML against DTD
if options.schemacheck:
	dtd = libxml2.parseDTD(None, options.schemacheck)
	ctxt = libxml2.newValidCtxt()
	ret = doc.validateDtd(ctxt, dtd)
	if ret != 1:
		print "error doing DTD validation"
		sys.exit(1)
	dtd.freeDtd()
	del dtd
	del ctxt


# Check XML file basics
(status, statusstring) = xml_check_version(doc)
debug(1, options.verb, statusstring)
if not status:
	print statusstring
	sys.exit(127)


# Get timestamp and check it
filetimestamp = xml_get_timestamp(doc)
if not filetimestamp:
	print 'No timestamp found in XML file, exiting because of invalid XML data...'
	sys.exit(127)

timedelta = int(now) - int(filetimestamp)
debug(1, options.verb, 'Age of XML file: %s seconds, max allowed: %s seconds' % (timedelta, options.seconds))


# Put XML to Python dict
checks = xml_to_dict(doc, options.verb, options.host, options.service)

# Loop over check results and perhaps mark them as outdated
for check in checks:
	check = check_mark_outdated(check, now, options.seconds, options.markold)


# Next steps depend on mode, output results
# MODE: passive
if options.mode == 'passive' or options.mode == 'passive_check':
	count_services = 0
	# Prepare
	if options.verb <= 2:
		pipe = open(options.pipe, "w")
	else:
		pipe = None

	# Output
	for check in checks:
		count_services += 1
		if check['service_description'] == None or check['service_description'] == '':
			# Host check
			line = '[%s] PROCESS_HOST_CHECK_RESULT;%s;%s;%s' % (now, check['host_name'], check['returncode'], check['output'].replace('\n', '\\n'))
		else:
			# Service check
			line = '[%s] PROCESS_SERVICE_CHECK_RESULT;%s;%s;%s;%s' % (now, check['host_name'], check['service_description'], check['returncode'], check['output'].replace('\n', '\\n'))

		if pipe:
			pipe.write(line + '\n')
		debug(2, options.verb, '%s / %s: %s - "%s"' % (check['host_name'], check['service_description'], check['returncode'], check['output'].replace('\n', '\\n')))
		debug(3, options.verb, line)

	# Close
	if pipe:
		pipe.close()
	else:
		print "Passive check results NOT written to Nagios pipe due to -vvv!"

	# Return/Exit as a Nagios Plugin if called with mode 'passive_check'
	if options.mode == 'passive_check':
		returncode   = 0
		returnstring = 'OK'
		output       = ''

		if options.markold:
			if (now - filetimestamp) > options.seconds:
				returnstring = 'WARNING'
				output = '%s check results written, which are %s(>%s) seconds old' % (count_services, (now-filetimestamp), options.seconds)
				returncode = 1

		if not output:
			output = '%s check results written which are %s seconds old' % (count_services, (now-filetimestamp))

		print 'Nag(ix)SC %s - %s' % (returnstring, output)
		sys.exit(returncode)

# MODE: checkresult
elif options.mode == 'checkresult' or options.mode == 'checkresult_check':
	count_services = 0
	count_failed   = 0

	chars = string.letters + string.digits

	for check in checks:
		count_services += 1
		if check.has_key('timestamp'):
			timestamp = check['timestamp']
		else:
			timestamp = xml_get_timestamp(xmldoc)

		filename = os.path.join(options.checkresultdir, 'c' + ''.join([random.choice(chars) for i in range(6)]))
		try:
			crfile = open(filename, "w")
			if check['service_description'] == None or check['service_description'] == '':
				# Host check
				crfile.write('### Active Check Result File ###\nfile_time=%s\n\n### Nagios Service Check Result ###\n# Time: %s\nhost_name=%s\ncheck_type=0\ncheck_options=0\nscheduled_check=1\nreschedule_check=1\nlatency=0.0\nstart_time=%s.00\nfinish_time=%s.05\nearly_timeout=0\nexited_ok=1\nreturn_code=%s\noutput=%s\n' % (timestamp, datetime.datetime.now().ctime(), check['host_name'], timestamp, timestamp, check['returncode'], check['output'].replace('\n', '\\n') ) )
			else:
				# Service check
				crfile.write('### Active Check Result File ###\nfile_time=%s\n\n### Nagios Service Check Result ###\n# Time: %s\nhost_name=%s\nservice_description=%s\ncheck_type=0\ncheck_options=0\nscheduled_check=1\nreschedule_check=1\nlatency=0.0\nstart_time=%s.00\nfinish_time=%s.05\nearly_timeout=0\nexited_ok=1\nreturn_code=%s\noutput=%s\n' % (timestamp, datetime.datetime.now().ctime(), check['host_name'], check['service_description'], timestamp, timestamp, check['returncode'], check['output'].replace('\n', '\\n') ) )
			crfile.close()

			# Create OK file
			open(filename + '.ok', 'w').close()
		except:
			count_failed += 1
			if options.mode == 'checkresult':
				print 'Could not write checkresult files "%s(.ok)" for "%s"/"%s"!' % (filename, check['host_name'], check['service_description'])

	if options.mode == 'checkresult_check':
		returnstring = ''
		output       = ''
		if count_failed == 0:
			returnstring = 'OK'
			returncode   = 0
			output       = 'Wrote checkresult files for %s services' % count_services
		elif count_failed == count_services:
			returnstring = 'CRITICAL'
			returncode   = 2
			output       = 'No checkresult files could be writen!'
		else:
			returnstring = 'WARNING'
			returncode   = 1
			output       = 'Could not write %s out of %s checkresult files!' % (count_failed, count_services)

		print 'Nag(ix)SC %s - %s' % (returnstring, output)
		sys.exit(returncode)

	if count_failed == 0:
		sys.exit(0)
	else:
		sys.exit(1)

# MODE: active
elif options.mode == 'active':

	if len(checks) > 1:
		print 'Nag(ix)SC UNKNOWN - Found more (%s) than one host/service!' % len(checks)
		sys.exit(3)
	elif len(checks) == 0:
		print 'Nag(ix)SC UNKNOWN - No check for "%s"/"%s" found in XML' % (options.host, options.service)
		sys.exit(3)

	print checks[0]['output']
	sys.exit(int(checks[0]['returncode']))

else:
	print 'Unknown mode! This should NEVER happen!'
	sys.exit(127)
