# sysmonitor.py
# -*- coding: utf8 -*-

# Copyright (c) 2010 Fondazione Ugo Bordoni.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from SysProf import LocalProfilerFactory
from SysProf.NemesysException import LocalProfilerException, RisorsaException, FactoryException
from logger import logging
from errorcoder import Errorcoder
from xml.etree import ElementTree as ET

import checkhost
import netifaces
import paths
import platform
import socket
import sysmonitorexception


platform_name = platform.system().lower()
if platform_name == 'windows':
  from SysProf.windows import profiler
elif platform_name == 'darwin':
  from SysProf.darwin import profiler
else:
  from SysProf.linux import profiler
 
 
STRICT_CHECK = True

tag_results = 'SystemProfilerResults'
tag_threshold = 'SystemProfilerThreshold'
tag_avMem = 'RAM.totalPhysicalMemory'
tag_memLoad = 'RAM.RAMUsage'
tag_wireless = 'wireless.ActiveWLAN'
tag_ip = 'ipAddr' #to check
tag_sys = 'sistemaOperativo.OperatingSystem'
tag_cpu = 'CPU.cpuLoad'
tag_mac = 'rete.NetworkDevice/MACAddress'
tag_activeNic = 'rete.NetworkDevice/isActive'
tag_cores = 'CPU.cores'
tag_proc = 'CPU.processor'
tag_hosts = 'hostNumber'
#tag_wireless = 'rete.NetworkDevice/Type'


#' SOGLIE '#
th_host = 1           # Massima quantità di host in rete
th_avMem = 134217728  # Minima memoria disponibile
th_memLoad = 95       # Massimo carico percentuale sulla memoria
th_cpu = 85           # Massimo carico percentuale sulla CPU
#'--------'#


logger = logging.getLogger()
errors = Errorcoder(paths.CONF_ERRORS)


def _get_values(tagrisorsa, xmlresult, tag = tag_results):
  #' Estrae informazioni dal SystemProfiler '#
  values = {}
  try:
    for subelement in xmlresult.find(tagrisorsa):
      values.update({subelement.tag:subelement.text})
  except Exception as e:
    logger.warning('Errore durante il recupero dello stato del computer. %s' % e)
    raise Exception('Errore durante il recupero dello stato del computer.')

  return values


def _get_status(res):

  logger.debug('Recupero stato della risorsa %s' % res)
  data = ET.ElementTree()
  
  try:
      profiler = LocalProfilerFactory.getProfiler()
      data = profiler.profile(set([res]))
  except FactoryException as e:
    logger.error ('Problema nel tentativo di istanziare la classe: %s' % e)
    raise sysmonitorexception.FAILPROF
  except RisorsaException as e:
    logger.error ('Problema nel tentativo di istanziare la risorsa: %s' % e)
    raise sysmonitorexception.FAILPROF
  except LocalProfilerException as e:
    logger.error ('Problema nel tentativo di istanziare il profiler: %s' % e)
    raise sysmonitorexception.FAILPROF
  except Exception as e:
    logger.error('Non sono riuscito a trovare lo stato del computer con SystemProfiler: %s.' % e)
    raise sysmonitorexception.FAILPROF

  return _get_values(res, data)


def _get_string_tag(tag, value, res):

  values = _get_status(res)

  try:
    value = str(values[tag])
  except Exception as e:
    logger.error('Errore in lettura del paramentro "%s" di SystemProfiler: %s' % (tag, e))
    if STRICT_CHECK:
      raise sysmonitorexception.FAILREADPARAM

  if value == 'None':
    return None

  return value


def _get_float_tag(tag, value, res):

  values = _get_status(res)

  if (value == None):
    logger.error('Errore nel valore del paramentro "%s" di SystemProfiler.' % tag)
    raise sysmonitorexception.FAILREADPARAM

  try:
    value = float(values[tag])
  except Exception as e:
    logger.error('Errore in lettura del paramentro "%s" di SystemProfiler: %s' % (tag, e))
    if STRICT_CHECK:
      raise sysmonitorexception.FAILREADPARAM

  return value


def _check_cpu():
  
  value = _get_float_tag(tag_cpu.split('.', 1)[1], th_cpu - 1, tag_cpu.split('.', 1)[0])
  
  if value < 0 or value > 100:
    raise sysmonitorexception.BADCPU

  if value > th_cpu:
    raise sysmonitorexception.WARNCPU

  return value


def _check_mem():

  avMem = _get_float_tag(tag_avMem.split('.')[1], th_avMem + 1, tag_avMem.split('.')[0])
  if avMem < 0:
    raise sysmonitorexception.BADMEM
  if avMem < th_avMem:
    raise sysmonitorexception.LOWMEM

  memLoad = _get_float_tag(tag_memLoad.split('.')[1], th_memLoad - 1, tag_memLoad.split('.')[0])
  if memLoad < 0 or memLoad > 100:
    raise sysmonitorexception.INVALIDMEM
  if memLoad > th_memLoad:
    raise sysmonitorexception.OVERMEM
  
  memData = 'Used %s%% of %d MB' % (memLoad, avMem/1024)

  return memData


def _check_wireless():
  
  wifi = 'Wireless LAN inattiva.'
  profiler = LocalProfilerFactory.getProfiler()
  data = profiler.profile(set(['rete']))
  
  for device in data.findall('rete/NetworkDevice'):
    logger.debug(ET.tostring(device))
    status = device.find('Status').text
    if (status == 'Enabled'):
        type = device.find('Type').text
        if (type == 'Wireless'):
            raise sysmonitorexception.WARNWLAN
          
  return wifi


def _check_hosts(up = 2048, down = 2048, ispid = 'tlc003', arping = 1):

  ip = getIp();
  mac = _get_Mac(ip)
  mask = _get_Mask(ip)
  logger.info('| Mac: %s | Ip: %s | Cidr Mask: %d |' % (mac, ip, mask))

  if (arping == 0):
    thres = th_host + 1
  else:
    thres = th_host

  value = checkhost.countHosts(ip, mask, up, down, ispid, thres, arping, mac)
  logger.info('Trovati %d host in rete.' % value)

  if value < 0:
    raise sysmonitorexception.BADHOST
  elif (value == 0):
    if arping == 1:
      logger.warning('Passaggio a PING per controllo host in rete')
      return _check_hosts(up, down, ispid, 0)
    else:
      raise sysmonitorexception.BADHOST
  elif value > thres:
    logger.error('Presenza di altri %s host in rete.' % value)
    raise sysmonitorexception.TOOHOST
      
  return value


def _check_ip_syntax(ip):

  try:
    socket.inet_aton(ip)
    parts = ip.split('.')
    if len(parts) != 4:
      return False
  except Exception:
    return False

  return True


def _convertDecToBin(dec):
  i = 0
  bin = range(0, 4)
  for x in range(0, 4):
    bin[x] = range(0, 8)

  for i in range(0, 4):
    j = 7
    while j >= 0:

      bin[i][j] = (dec[i] & 1) + 0
      dec[i] /= 2
      j = j - 1
  return bin


def _mask_conversion(dotMask):
  nip = str(dotMask).split(".")
  if(len(nip) == 4):
    i = 0
    bini = range(0, len(nip))
    while i < len(nip):
      bini[i] = int(nip[i])
      i += 1
    bins = _convertDecToBin(bini)
    lastChar = 1
    maskcidr = 0
    i = 0
    while i < 4:
      j = 0
      while j < 8:
        if (bins[i][j] == 1):
          if (lastChar == 0):
            return 0
          maskcidr = maskcidr + 1
        lastChar = bins[i][j]
        j = j + 1
      i = i + 1
  else:
    return 0
  return maskcidr


def _get_NetIF():
  
  netIF = {}
  
  for ifName in netifaces.interfaces():
    ip = [i['addr'] for i in netifaces.ifaddresses(ifName).setdefault(netifaces.AF_INET, [{'addr':'No IP addr'}] )]
    mask = [i['netmask'] for i in netifaces.ifaddresses(ifName).setdefault(netifaces.AF_INET, [{'netmask':'No IP addr'}] )]
    mac = [i['addr'] for i in netifaces.ifaddresses(ifName).setdefault(netifaces.AF_LINK, [{'addr':'No IP addr'}] )]
    netIF[ifName] = {'mac':mac,'ip':ip,'mask':mask}
  
  #logger.debug('Network Interfaces:\n %s' %netIF)
    
  return netIF


def _get_ActiveIp(host = 'finaluser.agcom244.fub.it', port = 443):

  logger.info('Determinazione dell\'IP attivo verso Internet')

  s = socket.socket(socket.AF_INET)
  s.connect((host, port))
  value = s.getsockname()[0]

  if not _check_ip_syntax(value):
    raise sysmonitorexception.UNKIP
  
  return value


def _get_Mac(ip = _get_ActiveIp()):
  
  mac = None
  netIF = _get_NetIF()

  for interface in netIF:
    if (netIF[interface]['ip'][0] == ip):
      #logger.debug('| Ip: %s | Mac: %s |' % (ip,netIF[interface]['mac'][0]))
      mac = netIF[interface]['mac'][0]
  
  if (mac == None):
    logger.error('Impossibile recuperare il valore del mac address dell\'IP %s' % ip)
    raise sysmonitorexception.BADMAC
  
  return mac


def getIp():
  
  ip = None
  netIF = _get_NetIF()
  activeIp = _get_ActiveIp()
  
  for interface in netIF:
    if (netIF[interface]['ip'][0] == activeIp):
      #logger.debug('| Active Ip: %s | Find Ip: %s |' % (activeIp,netIF[interface]['ip'][0]))
      ip = activeIp
  
  if (ip==None):
    raise sysmonitorexception.UNKIP
    
  return ip
  

def _get_Mask(ip = _get_ActiveIp()):

  cidrMask = 0
  dotMask = None
  netIF = _get_NetIF()

  for interface in netIF:
    if (netIF[interface]['ip'][0] == ip):
      #logger.debug('| Ip: %s | Mask: %s |' % (ip,netIF[interface]['mask'][0]))
      dotMask = netIF[interface]['mask'][0]
      cidrMask = _mask_conversion(dotMask)
  
  if (cidrMask <= 0):
    logger.error('Impossibile recuperare il valore della maschera dell\'IP %s' % ip)
    raise sysmonitorexception.BADMASK
  
  return cidrMask


def _get_Os():
  
  d = {tag_sys:''}
  r = []

  for keys in d:
    r.append(_get_string_tag(keys.split('.', 1)[1], 1, keys.split('.', 1)[0]))

  return r


def _get_Sys():
  
  d = {tag_sys:'', tag_cores:'', tag_proc:''}
  r = []

  for keys in d:
    r.append(_get_string_tag(keys.split('.', 1)[1], 1, keys.split('.', 1)[0]))

  return r


def checkset(check_set=set()):
  
  available_check =\
  {                                           \
   'CPU':{'prio':1,'meth':_check_cpu},        \
   'RAM':{'prio':2,'meth':_check_mem},        \
   'rete':{'prio':3,'meth':_check_wireless},  \
   'hosts':{'prio':4,'meth':_check_hosts},    \
   'mac':{'prio':5,'meth':_get_Mac},            \
   'ip':{'prio':6,'meth':getIp},              \
   'os':{'prio':7,'meth':_get_Os},              \
   #'sys':{'prio':8,'meth':_get_Sys}             \
  }
  
  system_profile = {}
  
  if (len(check_set) > 0):
    checks = (check_set & set(available_check.keys()))
    
    unavailable_check = check_set - set(available_check.keys())
    if (unavailable_check):
      for res in list(unavailable_check):
        system_profile[res]={}
        system_profile[res]['status']=None
        system_profile[res]['info']='Risorsa non disponibile'
        
  else:
    checks = set(available_check.keys())
  
  logger.debug('Check Order: %s' % sorted(available_check, key=lambda res: available_check[res]['prio']))
  for check in sorted(available_check, key=lambda check: available_check[check]['prio']):
    if check in checks:
      
      try:
        info = None
        status = None
        info = available_check[check]['meth']()
        if (info!=None):
          status = True
      except Exception as e:
        errorcode = errors.geterrorcode(e)
        logger.error('Errore [%d]: %s' % (errorcode, e))
        info = e
        status = False
      
      system_profile[check]={}
      system_profile[check]['status']=status
      system_profile[check]['info']=str(info)
      logger.info('%s: %s' % (check,system_profile[check]))
      
  return system_profile


def fastcheck():
 
  _check_cpu()
  _check_mem()

  return True


def mediumcheck():

  fastcheck()
  _check_wireless()

  return True


def checkall(up, down, ispid, arping = 1):

  mediumcheck()
  _check_hosts(up, down, ispid, arping)
  
  return True




if __name__ == '__main__':

  try:
    print '\nCheck All'
    print 'Test sysmonitor checkall: %s' % checkall(1000, 2000, 'fst001')
  except Exception as e:
    errorcode = errors.geterrorcode(e)
    print 'Errore [%d]: %s' % (errorcode, e)
  
  print '\nCheck Set All'
  print 'Test sysmonitor checkset: %s' % checkset()
  print '\nCheck Set Partial'
  print 'Test sysmonitor checkset: %s' % checkset(set(['CPU','RAM','rete','mac','ip','pippo',8]))
  
  