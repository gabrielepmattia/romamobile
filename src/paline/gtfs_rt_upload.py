# coding: utf-8

#
#    Copyright 2015-2016 Roma servizi per la mobilità srl
#    Developed by Luca Allulli
#
#    This file is part of Roma mobile.
#
#    Roma mobile is free software: you can redistribute it
#    and/or modify it under the terms of the GNU General Public License as
#    published by the Free Software Foundation, version 2.
#
#    Roma mobile is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
#    or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
#    for more details.
#
#    You should have received a copy of the GNU General Public License along with
#    Roma mobile. If not, see http://www.gnu.org/licenses/.
#

import settings

# paramiko e' importato dentro le funzioni, non qui in cima, e non e' piu' fra le
# dipendenze installate. Questo upload e' spento: l'unica chiamata, in
# tpl.Aggiornatore.run(), e' commentata, e i settings che gli servono
# (WEBSERVER_HOST/USER/PASSWORD) non esistono. Tenere l'import a livello di modulo
# obbligava a installare paramiko, che a sua volta si tira dietro pycrypto —
# abbandonato e con CVE note. Chi riattiva questa funzione otterra' un ImportError
# esplicito e sapra' cosa installare.


def createSSHClient(server, user, password, port=22):
	import paramiko
	client = paramiko.SSHClient()
	client.load_system_host_keys()
	client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
	client.connect(server, port, user, password)
	return client



def gtfs_realtime_uploader(g):
	import paramiko
	with open("gtfs_rt.txt", "w") as f:
		f.write(str(g))
	with open("gtfs_rt.bin", "w") as f:
		f.write(g.SerializeToString())

	ssh = createSSHClient(settings.WEBSERVER_HOST, settings.WEBSERVER_USER, settings.WEBSERVER_PASSWORD)
	sftp = paramiko.SFTPClient.from_transport(ssh.get_transport())
	sftp.put('./gtfs_rt.txt', '/gtfs_rt.txt')
	sftp.put('./gtfs_rt.bin', '/gtfs_rt.bin')
	sftp.close()
	ssh.close()


