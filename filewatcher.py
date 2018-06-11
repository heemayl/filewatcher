#!/usr/bin/env python3

#
# filewatcher.py
#
# filewatcher.py watches file(s) and sends mail and/or
# logs to syslog when the changed portion of the file(s)
# matches the given Regex pattern.
#
# Copyright © 2018 Readul Hasan Chayan <me@heemayl.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#


import argparse
import collections
import functools
import multiprocessing
import re
import shlex
import smtplib
import subprocess
import time


class FileWatcherException(Exception):
    '''Custom Exception class.'''
    pass


def parse_arguments():
    '''Parses arguments and returns valid arguments dict.'''
    parser = argparse.ArgumentParser(
        prog='filewatcher',
        description=(
            'The watchdog that watches files for any modifications, '
            'and sends mail and/or logs to syslog when the appended '
            'portion matches the input Regex. Filewatcher assumes the '
            'mail server is listening on localhost:25 without any '
            'authentication'
        ),
    )

    parser.add_argument('-r', '--regex',
                        dest='regex',
                        required=True,
                        help=(
                            'The Python Regular Expression pattern to match'
                        )
    )
    parser.add_argument('-f', '--file',
                        dest='watch_files',
                        nargs='+',
                        required=True,
                        help=(
                            'Files to watch. Multiple files are '
                            'supported'
                        )
    )
    parser.add_argument('-s', '--syslog',
                        dest='syslog',
                        action='store_true',
                        required=False,
                        help=(
                            'Log to syslog. The default is '
                            'not to send anything to syslog'
                        )
    )
    parser.add_argument('--from',
                        dest='from_addr',
                        required=False,
                        help=(
                            'The email address to send mail from. '
                            'Logwatcher does not check validity of '
                            'entered address'
                        )
    )
    parser.add_argument('--to',
                        dest='to_addrs',
                        nargs='+',
                        required=False,
                        help=(
                            'The email addresses to send mail to. '
                            'Multiple addresses are supported. '
                            'Logwatcher does not check validity of '
                            'entered addresses.'
                        )
    )

    args_ns = parser.parse_args()
    args_dict = vars(args_ns)
    return args_dict


def _run_command(command, shell=True):
    '''Takes a command string and after running the
    command returns a tuple containing the exit
    status, STDOUT and STDERR.
    '''
    command = command if shell else shlex.split(command)
    popen_obj = subprocess.Popen(
        command,
        shell=shell,
        bufsize=0,  # unbuffered
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = popen_obj.communicate()
    returncode = popen_obj.wait()

    return (
        returncode,
        stdout.decode('utf-8').strip(),
        stderr.decode('utf-8').strip()
    )
    

def send_mail(from_addr, to_addrs, subject, body):
    '''Takes required parameters and sends an email.'''
    to_addrs_str = ', '.join(to_addrs)
    subject = 'Filewatcher: {}'.format(subject)
    body = 'Mail sent by filewatcher.\n\n{}\n'.format(body)

    message = 'From: {}\nTo: {}\nSubject: {}\n\n{}\n'.format(
        from_addr, to_addrs_str, subject, body)

    try:
        smtp_client = smtplib.SMTP('localhost', 25)
        smtp_client.sendmail(from_addr, to_addrs, message)
    finally:
        smtp_client.close()
            

def log_syslog(message):
    '''Logs message to syslog. Returns True
    if succeeds, False otherwise.'''
    command = '/usr/bin/logger --priority local0.info \
                filewatcher: {}'.format(message)
    if _run_command(command, shell=False)[0] == 0:
        return True
    return False


def check_input_combo(one, two, exc_msg):
    '''If one is True, two must be True; Otherwise
    FileWatcherException is raised with the given
    exception message.
    '''
    if one:
        if not two:
            raise FileWatcherException(exc_msg)
    return True


def base_verifier_sender(new_lines, syslog, from_addr, to_addrs, regex, file_):
    '''Checks for the match in new_lines; if found, logs
    to syslog, and/or send mail based in input args.
    '''
    # Matched lines dict with line_no as key
    # and line string as value
    matched_lines = collections.OrderedDict()
    for line in new_lines:
        try:
            line_no, line = line.split(maxsplit=1)
        except ValueError:
            continue
        if regex.search(line):
            matched_lines[line_no] = line

    if matched_lines:
        matched_lines_str = '\n'.join([
            'line_no:{}::{}'.format(line_no, line)
            for line_no, line in matched_lines.items()
        ])
        if syslog:
            log_syslog('file: {}:: {}'.format(
                file_, matched_lines_str)
            )
        if from_addr:
            send_mail(
                from_addr,
                to_addrs,
                'Regex pattern {} matched in {}'.format(
                    regex.pattern, file_
                ),
                'Regex: {}\nFile: {}\n\n{}\n'.format(
                    regex.pattern,
                    file_,
                    matched_lines_str
                )
            )
        

def base_watcher(file_, regex, syslog, from_addr, to_addrs):
    '''Takes a compiled Regex and a file to  watch; sets
    watches on the file using inotifywait (uses inotify(2)).
    Checks if the appended content matches the given Regex
    pattern; if so, send_mail and/or log_syslog.
    '''
    if not any([syslog, from_addr, to_addrs]):
        raise FileWatcherException(
            'No syslog or send mail arguments specified'
        )

    check_input_combo(from_addr, to_addrs,
                      'No mail send to address(es) specified')
    check_input_combo(to_addrs, from_addr,
                      'No mail from address specified')

    # Set up commands
    inotify_cmd = (
        'inotifywait --quiet --monitor -- {} | '.format(file_)
        + 'grep -qi MODIFY'
    )
    tail_cmd = 'nl -ba {file_} | tail -n +{line_no}'.format
    tail_cmd_partial = functools.partial(
        tail_cmd, file_=file_
    )
    # Line offset seen/processed so far
    line_no = 0

    while True:
        if _run_command(inotify_cmd, shell=True)[0] == 0:
            # Splitted new lines with line no
            new_lines_ = _run_command(
                tail_cmd_partial(line_no=line_no + 1)
            )[1].splitlines()
            
            # Set line_no
            try:
                line_no = int(new_lines_[-1].split()[0])
            # File truncated
            except IndexError:
                line_no = 1
            
            base_verifier_sender(
                new_lines_, syslog, from_addr, to_addrs, regex, file_
            )
        time.sleep(0.1)


def mp_error_callback(exc):
    '''For any error from the multiprocessing
    map_async, this function is called with the
    exception as the argument. Here, logging
    the exception to syslog.
    '''
    return log_syslog('filewatcher: {}'.format(str(exc)))


def main():
    '''Main function that acts as
    a co-ordinator of all tasks.
    '''
    args_dict = parse_arguments()
    regex = re.compile(r'{}'.format(args_dict.get('regex')))
    syslog = args_dict.get('syslog', False)
    from_addr = args_dict.get('from_addr', '')
    to_addrs = args_dict.get('to_addrs', [])
    watch_files = args_dict.get('watch_files')

    base_watcher_partial = functools.partial(
        base_watcher,
        # Applied args
        regex=regex,
        syslog=syslog,
        from_addr=from_addr,
        to_addrs=to_addrs,
    )

    # Multiprocessing pool with spawning capability of
    # len(watch_files) subprocesses at a time
    mp_pool = multiprocessing.Pool(processes=len(watch_files))
    result = mp_pool.map_async(
        base_watcher_partial,
        watch_files,
        error_callback=mp_error_callback
    )
    result.wait()
    return vars(result).get('_success', True)
    

if __name__ == '__main__':
    main()

