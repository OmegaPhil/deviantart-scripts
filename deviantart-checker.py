#!/usr/bin/env python3

'''
Version 0.5 2015.03.21
Copyright (c) 2014-2015, OmegaPhil - OmegaPhil@startmail.com

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


GPL_NOTICE = '''
Copyright (C) 2014-2016 OmegaPhil
License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
'''

# pylint: disable=missing-docstring, no-self-use, too-few-public-methods
# pylint: disable=too-many-arguments

config = {}


def generate_command_fragments(command, subject, message):

    # Substituting values into command to call in the normal way for
    # the subject since that is essentially fixed - content is not
    # fixed and can contain quotes and speechmarks. I have tried to
    # escape such stuff with shlex.quote, but it can't cope in
    # examples of single quotes, and when a full command is quoted
    # it doesn't execute correctly. Given that I don't want this going
    # through a shell, I should be able to give command parameters
    # straight to the called process without weird escaping - which is
    # what I am doing here
    command = command.replace('%s', '[deviantart-checker] ' + subject)
    return [fragment.replace('%m', message) for fragment in
            shlex.split(command)]


def handle_unknown_error(err):

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

    global config  # pylint: disable=global-statement

    # Loading configuration if it exists
    config_directory = os.path.expanduser('~/.config/deviantart-checker')
    config_file_path = os.path.join(config_directory, 'deviantart-checker.conf')
    if os.path.exists(config_file_path):

        # Loading YAML document
        try:
            with io.open(config_file_path, 'r') as config_file:
                config = yaml.load(config_file, yaml.CLoader)
            if config is None:
                raise Exception('YAML document empty')
        except Exception as e:
            raise Exception('Unable to load config from YAML document '
                            '(\'%s\'):\n\n%s\n\n%s\n'
                            % (config_file_path, str(e),
                               traceback.format_exc()))

    # Ensuring required settings exist
    if 'username' not in config or 'password' not in config:
        raise Exception('Please ensure a deviantART username and password is '
                        'configured in \'%s\'' % config_file_path)
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

    # Can't get the indentation to pylint's liking
    # pylint: disable=bad-continuation
    # Validating apply_whitelist_to
    if (('apply_whitelist_to' not in config or
         not config['apply_whitelist_to']
        ) and
        'notification_whitelist' in config and
        config['notification_whitelist']):
        print('config specifies notification_whitelist however '
              'apply_whitelist_to is not present or empty - whitelist will not '
              'be used', file=sys.stderr)
    for event in config['apply_whitelist_to']:
        if event not in ['comments', 'replies', 'unread_notes', 'deviations']:
            print('\'%s\' in \'apply_whitelist_to\' configuration is invalid -'
                  ' please use \'comments\'/\'replies\'/\'unread_notes\''
                  '/\'deviations\'' % event, file=sys.stderr)


def poll_service():

    # pylint: disable=too-many-locals,too-many-branches,too-many-statements

    # Logging in to deviantART - any errors here will be fatal and are handled
    # in the main scope
    dA = devart.DeviantArtService(config['username'], config['password'])
    state = devart.AccountState('~/.cache/deviantart-checker/state.txt')

    # Looping for regular message fetching
    while True:

        try:

            # Attempting to log in - errors at this level will be logged and the
            # program will simply wait until the next interval to try again
            if not dA.logged_in:
                dA.login()

            try:

                # Getting the current state of messages
                dA.get_messages(state)

            # Currently I'll treat all exceptions here as issues with
            # deviantART or an expired login - invalidate the login and report
            # on the issue but reraise waiting for the next loop run to react
            except Exception as e:
                dA.logged_in = False
                raise

            # Working out how the state has changed
            new_comments = devart.get_new(state, devart.COMMENTS)
            new_replies = devart.get_new(state, devart.REPLIES)
            new_unread_notes = devart.get_new(state, devart.UNREAD_NOTES)
            new_deviations = devart.get_new(state, devart.DEVIATIONS)

            # Setting default change reporting state based on whether there is
            # a notification whitelist in use, and then the particular events
            # affected
            notification_whitelist_comments = False
            notification_whitelist_replies = False
            notification_whitelist_unread_notes = False
            notification_whitelist_deviations = False
            if ('notification_whitelist' in config and
                    config['notification_whitelist'] and
                    'apply_whitelist_to' in config and
                    config['apply_whitelist_to']):
                if 'comments' in config['apply_whitelist_to']:
                    notification_whitelist_comments = True
                if 'replies' in config['apply_whitelist_to']:
                    notification_whitelist_replies = True
                if 'unread_notes' in config['apply_whitelist_to']:
                    notification_whitelist_unread_notes = True
                if 'deviations' in config['apply_whitelist_to']:
                    notification_whitelist_deviations = True

            # Summarise changes, and when a whitelist is in place, only
            # returning information if it includes something generated from a
            # person of interest
            # Filter is used to remove empty items, list is used to explicitly
            # evaluate immediately
            comments_change_title, comments_change_summary, comments_users = summarise_changes(new_comments, devart.COMMENTS)  # pylint: disable=line-too-long
            if ((notification_whitelist_comments and not set(config['notification_whitelist']).intersection(comments_users)) or  # pylint: disable=line-too-long
                    not comments_change_title):
                comments = ''
            else:
                comments = '%s:\n%s' % (comments_change_title,
                                        comments_change_summary)

            replies_change_title, replies_change_summary, replies_users = summarise_changes(new_replies, devart.REPLIES)  # pylint: disable=line-too-long
            if ((notification_whitelist_replies and not set(config['notification_whitelist']).intersection(replies_users)) or  # pylint: disable=line-too-long
                    not replies_change_title):
                replies = ''
            else:
                replies = '%s:\n%s' % (replies_change_title,
                                       replies_change_summary)

            unread_notes_change_title, unread_notes_change_summary, unread_notes_users = summarise_changes(new_unread_notes, devart.UNREAD_NOTES)  # pylint: disable=line-too-long
            if ((notification_whitelist_unread_notes and not set(config['notification_whitelist']).intersection(unread_notes_users)) or  # pylint: disable=line-too-long
                    not unread_notes_change_title):
                unread_notes = ''
            else:
                unread_notes = '%s:\n%s' % (unread_notes_change_title,
                                            unread_notes_change_summary)

            deviations_change_title, deviations_change_summary, deviations_users = summarise_changes(new_deviations, devart.DEVIATIONS)  # pylint: disable=line-too-long
            if ((notification_whitelist_deviations and not set(config['notification_whitelist']).intersection(deviations_users)) or  # pylint: disable=line-too-long
                    not deviations_change_title):
                deviations = ''
            else:
                deviations = '%s:\n%s' % (deviations_change_title,
                                          deviations_change_summary)

            # pylint: disable=bad-builtin
            title_bits = list(filter(None, [deviations_change_title,
                                            unread_notes_change_title,
                                            replies_change_title,
                                            comments_change_title]))
            content = list(filter(None, [deviations, unread_notes, replies,
                                         comments]))

            if content:

                try:
                    # pylint: disable=line-too-long
                    command_fragments = generate_command_fragments(config['command_to_run'],
                                                                   ", ".join(title_bits),
                                                                   "\n\n".join(content))

                    # Running command without a shell
                    subprocess.call(command_fragments)

                except Exception as e:  # pylint: disable=broad-except
                    raise Exception('Calling the command to run to notify changes '
                                    'failed:\n\n%s\n\n%s\n' %
                                    (config['command_to_run'], e))

        except Exception as e:  # pylint: disable=broad-except
            handle_unknown_error(e)

        time.sleep(config['update_every_minutes'] * 60)


def summarise_changes(messages, messages_type):

    # pylint: disable=redefined-outer-name, too-many-branches
    # pylint: disable=too-many-locals

    users = []

    # Returning null-length strings if no actual change has happened
    if not messages:
        return '', '', []

    # Dealing with different message types
    if messages_type == devart.COMMENTS or messages_type == devart.REPLIES:

        # Sorting comments on page they were posted under then the
        # timestamp - body is included so that it can be used later
        new_comments = sorted([(comment.title, comment.ts, comment.who,
                                comment.body)
                               for comment in messages],
                              key=lambda comment: (comment[0], comment[1],
                                                   comment[2], comment[3]))

        # Generating and returning summary
        current_title = None
        summary = []
        for title, _, who, body in new_comments:
            if current_title != title:
                summary.append('\nOn ' + title + ':\n')
                current_title = title
            summary.append('%s posted:\n%s' % (who, body))

            # Keeping record of users causing the updates
            if not who in users:
                users.append(who)

        if messages_type == devart.COMMENTS:
            messages_type_text = 'Comments'
        else:
            messages_type_text = 'Replies'
        return 'New ' + messages_type_text, '\n'.join(summary), users

    elif messages_type == devart.UNREAD_NOTES:

        # Sorting unread notes based on sender then title
        new_unread_notes = sorted([(note.sender, note.title, note.text)
                                   for note in messages],
                                  key=lambda note: (note[0], note[1]))

        # Generating and returning summary, now including note text
        current_sender = None
        summary = []
        for sender, title, text in new_unread_notes:
            if current_sender != sender:
                summary.append('\n' + sender + ' sent:\n')
                current_sender = sender
            summary += [title, '=' * len(title), text, '\n']

            # Keeping record of users causing the updates
            if not sender in users:
                users.append(sender)

        return 'New Unread Notes', '\n'.join(summary), users

    elif messages_type == devart.DEVIATIONS:

        # Generating case-insensitive sorted list of usernames and titles,
        # in that order
        new_deviations = sorted([(deviation.username, deviation.title)
                                 for deviation in messages],
                                key=lambda deviation: (deviation[0].lower(),
                                                       deviation[1].lower()))  # pylint: disable=line-too-long

        # Generating and returning summary
        current_username = None
        summary = []
        for username, title in new_deviations:
            if current_username != username:
                summary.append('\n' + username + ':\n')
                current_username = username
            summary.append(title)

            # Keeping record of users causing the updates
            if not username in users:
                users.append(username)

        return 'New Deviations', '\n'.join(summary), users

    else:

        # Invalid messages_type passed
        raise Exception('summarise_changes was called with an invalid '
                        'messages_type (%s)' % messages_type)


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
