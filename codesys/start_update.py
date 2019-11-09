#!/usr/bin/env python
import os
import urllib2


XML_FILE_NAME = 'robin.xml'


class ER(ExportReporter):
    def error(self, object, message):
        system.write_message(Severity.Error, "Error exporting %s: %s" % (object, message))
    def warning(self, object, message):
        system.write_message(Severity.Warning, "Warning exporting %s: %s" % (object, message))
    def nonexportable(self, object):
        system.write_message(Severity.Information, "Object not exportable: %s" % object)
    @property
    def aborting(self):
        return False;

# set working directory and check write permission
work_dir = os.popen('echo %TMP%').read().strip()
work_dir = work_dir + '\\' if work_dir[-1] != '\\' else work_dir
work_dir += 'robin_ros_codesys_bridge' + '\\'
try:
    os.mkdir(work_dir)
except OSError:
    pass

# get plink and pscp (python2 only)
work_dir_contents = os.listdir(work_dir)
for app in ['plink', 'pscp']:
    if app + '.exe' not in work_dir_contents:
        url = 'https://the.earth.li/~sgtatham/putty/latest/w32/{}.exe'.format(app)
        data = urllib2.urlopen(url).read()
        with open(work_dir + app + '.exe', 'wb') as file:
            file.write(data)

# save project and export xml
project = projects.primary
if project.dirty:
    res = system.ui.prompt("The project needs to be saved first. Proceed?", PromptChoice.YesNo, PromptResult.No);
    if res != PromptResult.Yes:
        system.ui.error('Update aborted.')
        raise SystemExit
    project.save()
project.export_xml(ER(), project.get_children(False), work_dir + XML_FILE_NAME, True)

location = 'criis@robin.local:catkin_ws'
pass_ = '5dpo'
target = 'criis@robin.local'
catkin_ws = '~/catkin_ws/'

# # get catkin workspace location
# location = ''
# while location.find('@') == -1 or location.find(':') == -1:
#     if location != '':
#         system.ui.error('Please provide location in the form: <user>@<address>:<path>')
#     location = system.ui.query_string("Catkin workspace location:\n( <user>@<address>:<path> )", cancellable=True) 
#     if location is None:
#         system.ui.error('Update aborted.')
#         raise SystemExit

# # parse location
# location = location.replace('\\', '/')
# location = location + '/' if location[-1] != '/' else location
# idx = location.find(':')
# target = location[:idx]
# catkin_ws = location[idx+1:]
# catkin_ws = '~/' + catkin_ws if catkin_ws[0] not in ['/', '~'] else catkin_ws

# # get password
# pass_ = system.ui.query_password("Password:", cancellable=True)
# if pass_ is None:
#     system.ui.error('Update aborted.')
#     raise SystemExit

# scan network
# gw = online.gateways['Gateway-1']
# gw.perform_network_scan()
# try:
#     online.gateways['Gateway-1'].perform_network_scan()
# except:
#     system.ui.error('Update failed.')
#     raise SystemExit
devices = projects.primary.find('Device', recursive=False)
if devices is None or len(devices) != 1:
    system.ui.error('Failed to find device.')
    raise SystemExit
guid = devices[0].get_gateway()
online.gateways[guid].perform_network_scan()

# online update / download
onlineapp = online.create_online_application()
was_logged_in = onlineapp.is_logged_in
if was_logged_in:
    onlineapp.logout()
onlineapp.login(OnlineChangeOption.Never, True)
onlineapp.logout()

# send xml and run update script
cmd = ' '.join(('cmd /c "',
                    'set RET=0',
                    '& echo. & echo Updating...',
                    '& {wd}plink.exe -ssh -batch -pw {pwd} {tgt} < {wd}{xml} "',
                        'cat > {ws}{xml}',
                        '&& cd {ws}',
                        '&& . *devel*/setup.bash',
                        '&& mv {xml} $(rospack find robin)/codesys/',
                        '&& roscd robin/codesys',
                        '&& ./update.py {ws}',
                        '&& echo && echo -n Restarting codesyscontrol...'
                        '&& echo {pwd} | sudo -S systemctl restart codesyscontrol 2> /dev/null',
                        '&& echo \\ Done.'
                    '" || set RET=1',
                    '& echo.',
                    '& pause',
                    '& exit %RET%',
                '"')).format(wd=work_dir, xml=XML_FILE_NAME, tgt=target, pwd=pass_, ws=catkin_ws)
if os.system(cmd) == 0:
    system.ui.info('Update finished successfully!')
else:
    system.ui.error('Update failed.')

# log back in
if was_logged_in:
    onlineapp.login(OnlineChangeOption.Keep, False)