#!/usr/bin/env python3
import socket
import subprocess
import sys
port='8080'
import os
port=os.environ.get('PORT',port)
print(f'Neste Mac: http://localhost:{port}')
print(f'Nome local (se mDNS funcionar): http://{socket.gethostname().split(".")[0]}.local:{port}')
addresses=set()
if sys.platform=='darwin':
 output=subprocess.run(['networksetup','-listallhardwareports'],capture_output=True,text=True).stdout
 for line in output.splitlines():
  if line.startswith('Device: '):
   device=line.split(': ',1)[1]
   value=subprocess.run(['ipconfig','getifaddr',device],capture_output=True,text=True).stdout.strip()
   if value:addresses.add(value)
else:
 try:addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
 except OSError:pass
for address in sorted(addresses):print(f'Rede local: http://{address}:{port}')
if not addresses:print('Sem IPv4 local detetado; liga o Mac à rede do evento.')
print('Telemóveis: mesma rede, sem isolamento entre clientes; permitir acesso na firewall quando o macOS pedir.')
