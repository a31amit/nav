"""
$Id$
$Source: /usr/local/cvs/navbak/navme/subsystem/statemon/lib/checker/SmbChecker.py,v $
"""
import os,re
from nav.statemon.abstractChecker import AbstractChecker
from nav.statemon.event import Event
pattern = re.compile(r'domain=\[[^\]]+\] os=\[([^\]]+)\] server=\[([^\]]+)\]',re.I) #tihihi
class SmbChecker(AbstractChecker):
	"""
	args:
	        'hostname'
		'username'
		'password'
		'port'
	"""
	def __init__(self,service, **kwargs):
		AbstractChecker.__init__(self, "smb", service, port=139, **kwargs)
	def execute(self):
		ip,port = self.getAddress()
		args = self.getArgs()
		host = args.get('hostname',ip)
		username = args.get('username','')
		password = args.get('password','')

		if password and username:
			s = '-U ' + username + '%' + password
		else:
			s = '-N'


		s = os.popen('/usr/bin/smbclient -L %s -p %i %s 2>/dev/null' % (host,port,s)).read()
		version = pattern.search(s) and ' '.join(pattern.search(s).groups())
		if version:
			self.setVersion(version)
			return Event.UP,'OK'
		else:
			return Event.DOWN,'error %s' % s.strip().split('\n')[-1]

def getRequiredArgs():
	"""
	Returns a list of required arguments
	"""
	requiredArgs = []
	return requiredArgs
								
