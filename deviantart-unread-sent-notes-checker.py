#!/usr/bin/env python3

'''
Version 0.1 2016.10.18
Copyright (c) 2016, OmegaPhil - OmegaPhil@startmail.com

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import datetime
import fcntl
import io
import numbers
import os
import os.path
import subprocess
import time
import traceback
import shlex
import sys

import yaml

import devart


config = {}


def generate_command_fragments(command, subject, message):
    '''Prepare command with variable substitution'''

    # Substituting values into command to call in the normal way for
    # the subject since that is essentially fixed - content is not
    # fixed and can contain quotes and speechmarks. I have tried to
    # escape such stuff with shlex.quote, but it can't cope in
    # examples of single quotes, and when a full command is quoted
    # it doesn't execute correctly. Given that I don't want this going
    # through a shell, I should be able to give command parameters
    # straight to the called process without weird escaping - which is
    # what I am doing here
    command = command.replace('%s', '[deviantart-unread-sent-notes-checker] '
                              + subject)
    return [fragment.replace('%m', message) for fragment in
            shlex.split(command)]


def handle_unknown_error(err):
    '''Handle unknown error'''

    # pylint: disable=line-too-long
    # I have decided to just log failures rather than die - this is
    # basically a service, and it is not acceptable for temporary
    # failures to stop the program doing its job - it must simply retry
    # after the usual delay
    # Examples of caught errors:
    # ConnectionError: HTTPSConnectionPool(host='www.deviantart.com', port=443): Max retries exceeded with url: /users/login (Caused by <class 'socket.error'>: [Errno 113] No route to host)
    # (<urllib3.connection.VerifiedHTTPSConnection object at 0x7f7f5f3a5e50>, 'Connection to www.deviantart.com timed out. (connect timeout=60)')
    error_message = 'Unhandled error \'%s\'\n\n%s' % (err, traceback.format_exc())
    print(error_message, file=sys.stderr)

    # Running command_to_run_on_failure if specified
    if config['command_to_run_on_failure']:

        try:
            command_fragments = generate_command_fragments(config['command_to_run_on_failure'],
                                                           'Error', error_message)

            # Running command without a shell
            subprocess.call(command_fragments)

        except Exception as e:  # pylint: disable=broad-except
            print('Calling the command to run on failure failed:\n\n%s\n'
                  '\n%s\n' % (config['command_to_run_on_failure'], e),
                  file=sys.stderr)


def load_config():
    '''Load config'''

    global config  # pylint: disable=global-statement

    # Loading configuration if it exists. Credentials has been split out into
    # its own file so that it can be shared amongst various scripts
    config_directory = os.path.expanduser('~/.config/deviantart-scripts')
    config_file_path = os.path.join(config_directory,
                                    'deviantart-unread-sent-notes-checker.conf')
    credentials_file_path = os.path.join(config_directory, 'credentials.conf')
    if (os.path.exists(config_file_path)
        and os.path.exists(credentials_file_path)):

        # Loading YAML documents - theres no need for them to be genuinely
        # separate documents, so just sticking them together
        try:
            config_text = (io.open(config_file_path, 'r').read() + '\n' +
                            io.open(credentials_file_path, 'r').read())
            config = yaml.load(config_text, yaml.CLoader)
            if config is None:
                raise Exception('YAML documents empty')
        except Exception as e:
            raise Exception('Unable to load config from YAML documents '
                            '\'%s\' and \'%s\':\n\n%s\n\n%s\n'
                            % (config_file_path, credentials_file_path, str(e),
                               traceback.format_exc()))

    # Ensuring required settings exist
    if 'username' not in config or 'password' not in config:
        raise Exception('Please ensure a deviantART username and password is '
                        'configured in \'%s\'' % credentials_file_path)
    if 'command_to_run' not in config:
        raise Exception('Please ensure command_to_run is configured in \'%s\'' %
                        config_file_path)

    # Ensuring sensible defaults
    # Keep update delay at at least 5 minutes so as not to cause deviantART
    # unnecessary load
    if ('update_every_minutes' not in config or
            not isinstance(config['update_every_minutes'], numbers.Number) or
            not config['update_every_minutes'] >= 5):
        config['update_every_minutes'] = 5


def poll_service():
    '''Main loop'''

    # Logging in to deviantART - any errors here will be fatal and are handled
    # in the main scope
    dA = devart.DeviantArtService(config['username'], config['password'])

    # Looping for regular unread notes fetching
    current_unread_notes = []
    while True:

        try:

            # Attempting to log in - errors at this level will be logged and the
            # program will simply wait until the next interval to try again
            if not dA.logged_in:
                dA.login()

            try:

                # Getting the current unread sent notes
                latest_unread_notes = dA.get_unread_sent_notes()

            # Currently I'll treat all exceptions here as issues with
            # deviantART or an expired login - invalidate the login and report
            # on the issue but reraise waiting for the next loop run to react
            except Exception as e:
                dA.logged_in = False
                raise

            # Determining newly-read notes
            read_notes_change_summary = []
            read_notes = set(current_unread_notes) - set(latest_unread_notes)
            current_unread_notes = latest_unread_notes
            if read_notes:
                read_notes_change_summary.append('The following sent notes have'
                                                 ' now been read:')
                for read_note in read_notes:
                    timestamp = datetime.datetime.fromtimestamp(read_note.ts)
                    # timestamp = timestamp.strftime('%y/%m/%d %H:%M:%S')
                    note_details = ('\'%s\' sent to %s on %s'
                    % (read_note.title, read_note.recipient, timestamp))
                    read_notes_change_summary.append(note_details)

                try:
                    command_fragments = generate_command_fragments(
                        config['command_to_run'], 'Freshly-Read Notes',
                        "\n\n".join(read_notes_change_summary))

                    # Running command without a shell
                    subprocess.call(command_fragments)

                except Exception as e:  # pylint: disable=broad-except
                    raise Exception('Calling the command to run to notify read '
                                    'notes failed:\n\n%s\n\n%s\n' %
                                    (config['command_to_run'], e))

        except Exception as e:  # pylint: disable=broad-except
            handle_unknown_error(e)

        time.sleep(config['update_every_minutes'] * 60)


# Loading config
try:
    load_config()
except Exception as e:  # pylint: disable=broad-except
    print('Unable to load or invalid configuration file:\n\n%s' % e,
          file=sys.stderr)
    sys.exit(1)

with open(__file__) as f:
    try:

        # Only allow one instance at a time - exclusive lock on the script
        # itself rather than using a pidfile
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Start polling loop
        poll_service()

    except IOError as e:
        print('This script appears to already be running - please kill all '
              'other instances before running again', file=sys.stderr)
        sys.exit(1)

    except Exception as e:  # pylint: disable=broad-except
        handle_unknown_error(e)

    finally:

        # Release lock
        fcntl.flock(f, fcntl.LOCK_UN | fcntl.LOCK_NB)
