#!/usr/bin/env python3

'''
Version 0.3 2014.09.08
Copyright (c) 2014, OmegaPhil - OmegaPhil@startmail.com

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

import collections
import io
import numbers
import os
import os.path
import subprocess
import time
import traceback
import shlex
import sys

import bs4  # Beautiful Soup 4
import requests
import yaml


GPL_NOTICE = '''
Copyright (C) 2014 OmegaPhil
License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
'''

# pylint: disable=missing-docstring, no-self-use, too-few-public-methods
# pylint: disable=too-many-arguments

config = {}

COMMENTS = 0
REPLIES = 1
UNREAD_NOTES = 2
DEVIATIONS = 3


# Getting new-style class
class DeviantArtService(object):
    '''Access the deviantART webservice'''

    # pylint: disable=too-many-instance-attributes

    def __init__(self, username, password):
        self.__difi_url = 'https://www.deviantart.com/global/difi.php'
        self.__inbox_id = None
        self.__username = username
        self.__password = password
        self.__r = self.__s = None
        self.comments = self.comments_count = self.deviations = None
        self.deviations_count = self.replies = self.replies_count = None
        self.unread_notes = self.unread_notes_count = None
        self.old_comments = self.old_comments_count = None
        self.old_deviations = self.old_deviations_count = None
        self.old_replies = self.old_replies_count = None
        self.old_unread_notes = self.old_unread_notes_count = None
        self.logged_in = False
        self.__last_content = None

        # Loading previous state
        self.__load_state()


    def __fetch_inbox_id(self):

        # Obtain inbox folder ID from message center
        try:
            difi_url = 'https://www.deviantart.com/global/difi.php'
            payload = {'c[]': 'MessageCenter;get_folders',
                       't': 'json'}
            self.__r = self.__s.post(difi_url, params=payload, timeout=60)
            self.__r.raise_for_status()
        except Exception as e:
            raise Exception('Unable to get inbox folder ID:\n\n%s\n\n%s\n'
                            % (e, traceback.format_exc()))

        # Making sure difi response is valid
        response = self.__r.json()
        if not self.__validate_difi_response(response, 0):
            raise Exception('The DiFi page request for the inbox folder ID '
                            'succeeded but the DiFi request failed:\n\n%s\n'
                            % response)

        # Searching for first folder labeled as the inbox
        for folder in response['DiFi']['response']['calls'][0]['response']['content']:  # pylint: disable=line-too-long
            if folder['is_inbox']:
                self.__inbox_id = folder['folderid']
                break

        # Erroring if the inbox has not been found
        if self.__inbox_id is None:
            raise Exception('Unable to find inbox folder in Message Center '
                            'folders:\n\n%s\n' % response)


    def __load_state(self):

        # Making sure cache directory is present
        create_cache_directory()

        # Loading state if it exists
        cache_directory = os.path.expanduser('~/.cache/deviantart-checker')
        state_file_path = os.path.join(cache_directory, 'state.txt')
        if os.path.exists(state_file_path):

            # Loading YAML document
            try:
                with io.open(state_file_path, 'r') as state_file:
                    state = yaml.load(state_file, yaml.CLoader)
                if state is None:
                    raise Exception('YAML document empty')
            except Exception as e:
                raise Exception('Unable to load state from YAML document '
                                '(\'%s\'):\n\n%s\n\n%s\n'
                                % (state_file_path, e, traceback.format_exc()))

            # Configuring service
            self.comments = state.get('comments', [])
            self.comments_count = state.get('commentsCount', 0)
            self.deviations = state.get('deviations', [])
            self.deviations_count = state.get('deviationsCount', 0)
            self.replies = state.get('replies', [])
            self.replies_count = state.get('repliesCount', 0)
            self.unread_notes = state.get('unread_notes', [])
            self.unread_notes_count = state.get('unread_notesCount', 0)

        else:

            # Noting the fact no state is present
            print('No previous state to load - all counts set to 0')

            # Configuring service
            self.comments = []
            self.comments_count = 0
            self.deviations = []
            self.deviations_count = 0
            self.replies = []
            self.replies_count = 0
            self.unread_notes = []
            self.unread_notes_count = 0


    def __save_state(self):

        # Making sure cache directory is present
        create_cache_directory()

        # Saving state file
        try:
            cache_directory = os.path.expanduser('~/.cache/deviantart-checker')
            state_file_path = os.path.join(cache_directory, 'state.txt')
            state = {'comments': self.comments,
                     'commentsCount': self.comments_count,
                     'deviations': self.deviations,
                     'deviationsCount': self.deviations_count,
                     'replies': self.replies,
                     'repliesCount': self.replies_count,
                     'unread_notes': self.unread_notes,
                     'unread_notesCount': self.unread_notes_count}
            with io.open(state_file_path, 'w') as state_file:
                yaml.dump(state, state_file, yaml.CDumper)
        except Exception as e:
            raise Exception('Unable to save state into YAML document '
                            '(\'%s\'):\n\n%s\n\n%s\n'
                            % (state_file_path, e, traceback.format_exc()))


    def __validate_difi_response(self, response, call_numbers):

        # Making sure call_numbers is iterable - e.g. just one call number was
        # passed
        if not isinstance(call_numbers, collections.Sequence):
            call_numbers = [call_numbers]

        # Failing if overall call failed
        if response['DiFi']['status'] != 'SUCCESS':
            return False

        # Failing if any one call failed
        for call_number in call_numbers:
            if response['DiFi']['response']['calls'][call_number]['response']['status'] != 'SUCCESS':  # pylint: disable=line-too-long
                return False

        return True


    def get_messages(self):

        # Ensure I am logged in first
        if not self.logged_in:
            raise Exception('Please login before calling get_messages')

        # Making sure inbox ID is known first
        if self.__inbox_id is None:
            self.__fetch_inbox_id()

        # Fetch relevant unread notes, deviations etc
        try:

            # 100 is a limit for number of things returned - real limit is
            # >101 and <150
            payload = {'c[]': ['MessageCenter;get_views;' +
                               str(self.__inbox_id) + ',oq:fb_comments:0:100:f',
                               'MessageCenter;get_views;' +
                               str(self.__inbox_id) + ',oq:fb_replies:0:100:f',
                               'MessageCenter;get_views;' +
                               str(self.__inbox_id) + ',oq:notes_unread:0:100:f',  # pylint: disable=line-too-long
                               'MessageCenter;get_views;' +
                               str(self.__inbox_id) + ',oq:devwatch:0:100:f:'
                               'tg=deviations'],
                       't': 'json'}
            self.__r = self.__s.post(self.__difi_url, params=payload,
                                     timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to get number of unread notes, deviations'
                            ' etc:\n\n%s\n\n%s\n' % (e,
                                                     traceback.format_exc()))

        # Making sure difi response and all contained calls are valid
        response = self.__r.json()
        if not self.__validate_difi_response(response, range(4)):
            raise Exception('The DiFi page request to get number of unread '
                            'notes, deviations etc succeeded but the DiFi '
                            'request failed:\n\n%s\n' % response)

        # Copying current messages state to 'old' fields
        self.old_comments = self.comments[:]
        self.old_comments_count = self.comments_count
        self.old_replies = self.replies[:]
        self.old_replies_count = self.replies_count
        self.old_unread_notes = self.unread_notes[:]
        self.old_unread_notes_count = self.unread_notes_count
        self.old_deviations = self.deviations[:]
        self.old_deviations_count = self.deviations_count

        # Fetching and saving new message state. Note that replies are
        # basically comments so the class is reused
        self.comments = [Comment(int(hit['msgid']),
                                 extract_text(hit['title'], True),
                                 extract_text(hit['who'], True),
                                 int(hit['ts']), hit['url'],
                                 extract_text(hit['body']))
                         for hit in response['DiFi']['response']['calls'][COMMENTS]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        self.comments_count = response['DiFi']['response']['calls'][COMMENTS]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long
        self.replies = [Comment(int(hit['msgid']),
                                extract_text(hit['title'], True),
                                extract_text(hit['who'], True),
                                int(hit['ts']), hit['url'],
                                extract_text(hit['body']))
                        for hit in response['DiFi']['response']['calls'][REPLIES]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        self.replies_count = response['DiFi']['response']['calls'][REPLIES]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long

        self.unread_notes = [Note(int(hit['msgid']),
                                  extract_text(hit['title'], True),
                                  extract_text(hit['who'], True),
                                  int(hit['ts']))
                             for hit in response['DiFi']['response']['calls'][UNREAD_NOTES]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        self.unread_notes_count = response['DiFi']['response']['calls'][UNREAD_NOTES]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long
        self.deviations = [Deviation(hit['msgid'],
                                     extract_text(hit['title'], True),
                                     int(hit['ts']), hit['url'],
                                     extract_text(hit['username'], True))
                           for hit in response['DiFi']['response']['calls'][DEVIATIONS]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        self.deviations_count = response['DiFi']['response']['calls'][DEVIATIONS]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long
        self.__save_state()


#     def get_messages_and_notes_counts(self):
#
#         # Attempting to locate messages table cell
#         messagesCell = self.__last_content.find('td', id='oh-menu-split')
#         if messagesCell is None:
#             raise Exception('Unable to find messages cell on deviantART main '
#                             'page')
#
#         # Extracting messages and notes count
#         spans = messagesCell.findAll('span')
#         if len(spans) < 2:
#             raise Exception('Unable to find messages and/or notes count in '
#                             'messages cell on deviantART main page:\n\n%s\n'
#                             % messagesCell)
#         try:
#             messagesCount = int(spans[0].text)
#             notesCount = int(spans[1].text)
#         except Exception as e:
#             raise Exception('Unable to parse messages and/or notes count on '
#                             'deviantART main page - not valid numbers?\n\n'
#                             'spans: %s\n\n%s\n\n%s\n' %
#                             (spans, e, traceback.format_exc()))
#
#         # Returning counts
#         return (messagesCount, notesCount)


    def get_new(self, messages_type):

        # Dealing with different message types requested
        if messages_type == COMMENTS:
            return set(self.comments) - set(self.old_comments)
        elif messages_type == REPLIES:
            return set(self.replies) - set(self.old_replies)
        elif messages_type == UNREAD_NOTES:
            return set(self.unread_notes) - set(self.old_unread_notes)
        elif messages_type == DEVIATIONS:
            return set(self.deviations) - set(self.old_deviations)
        else:

            # Invalid messages_type passed
            raise Exception('get_new was called with an invalid messages_type'
                            ' (%s)' % messages_type)


    def last_page_content(self):
        return self.__last_content


    def login(self):

        # You need to fetch the login page first as the login form contains some
        # dynamic hidden fields. Using a Session object persists cookies and
        # maintains Keep-Alive
        try:
            login_url = 'https://www.deviantart.com/users/login'
            self.__s = requests.Session()
            self.__r = self.__s.get(login_url, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to load deviantART login page:\n\n%s\n\n%s'
                            '\n' % (e, traceback.format_exc()))

        # Parsing page
        self.__last_content = bs4.BeautifulSoup(self.__r.content)

        # Locating login form
        login_form = self.__last_content.find('form', id='form-login')
        if login_form is None:
            raise Exception('Unable to find login form on deviantART login'
                            ' page')

        # Obtaining hidden validation fields
        try:
            validate_token = login_form.find('input',
                                             attrs={'name': 'validate_token'}).get('value')  # pylint: disable=line-too-long
            validate_key = login_form.find('input',
                                           attrs={'name': 'validate_key'}).get('value')  # pylint: disable=line-too-long
        except Exception as e:
            raise Exception('Unable to fetch hidden validation field values in '
                            'deviantART\'s login form:\n\n%s\n\n%s\n'
                            % (e, traceback.format_exc()))

        # Debug code
        #print('validate_token: %s\nvalidate_key: %s'% (validate_token,
        #                                               validate_key))

        # Logging in to deviantART - this gets me the cookies that I can then
        # use elsewhere
        try:
            payload = {'username': self.__username,
                       'password': self.__password,
                       'validate_token': validate_token,
                       'validate_key': validate_key,
                       'remember_me': 1}
            self.__r = self.__s.post(login_url, data=payload, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to POST to deviantART login page:\n\n%s\n'
                            '\n%s\n' % (e, traceback.format_exc()))

        # Recording the fact we have now successfully logged in
        self.logged_in = True

        # Updating recorded page content
        self.__last_content = bs4.BeautifulSoup(self.__r.content)


    def summarise_changes(self, messages, messages_type):

        # pylint: disable=redefined-outer-name, too-many-branches
        # pylint: disable=too-many-locals

        users = []

        # Returning null-length strings if no actual change has happened
        if not messages:
            return '', '', []

        # Dealing with different message types
        if messages_type == COMMENTS or messages_type == REPLIES:

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

            if messages_type == COMMENTS:
                messages_type_text = 'Comments'
            else:
                messages_type_text = 'Replies'
            return 'New ' + messages_type_text, '\n'.join(summary), users

        elif messages_type == UNREAD_NOTES:

            # Sorting unread notes based on sender then title
            new_unread_notes = sorted([(note.who, note.title)
                                       for note in messages],
                                      key=lambda note: (note[0], note[1]))

            # Generating and returning summary
            current_sender = None
            summary = []
            for who, title in new_unread_notes:
                if current_sender != who:
                    summary.append('\n' + who + ' sent:\n')
                    current_sender = who
                summary.append(title)

                # Keeping record of users causing the updates
                if not who in users:
                    users.append(who)

            return 'New Unread Notes', '\n'.join(summary), users

        elif messages_type == DEVIATIONS:

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


# Note that this class is used for both comments and replies, as the latter
# are basically comments. Replies are called 'Feedback Messages' on dA
class Comment:

    # pylint: disable=too-few-public-methods, too-many-arguments

    def __init__(self, ID, title, who, ts, URL, body):

        self.ID = ID
        self.title = title  # This is a description of the page the comment is
                            # on
        self.who = who
        self.ts = ts
        self.URL = URL
        self.body = body

    def __hash__(self, *args, **kwargs):

        # Defining hashable interface based on ID so that the object can be
        # used in a set
        return self.ID

    def __eq__(self, other):

        # Required comparison operations for set membership etc
        return hash(self) == hash(other)

    def __neq__(self, other):

        # Required comparison operations for set membership etc
        return not self.__eq__(other)


class Deviation:

    # pylint: disable=too-few-public-methods

    def __init__(self, ID, title, ts, URL, username):

        self.ID = ID
        self.title = title
        self.ts = ts
        self.URL = URL
        self.username = username

    def __hash__(self, *args, **kwargs):

        # Defining hashable interface based on ID so that the object can be
        # used in a set. __hash__ must return an integer, however the
        # deviantART IDs seem to be a string in the form <number>:<number>
        return int(self.ID.split(':')[1])

    def __eq__(self, other):

        # Required comparison operations for set membership etc
        return hash(self) == hash(other)

    def __neq__(self, other):

        # Required comparison operations for set membership etc
        return not self.__eq__(other)


# Doesn't look like normal note content is made available in the difi call
class Note:

    def __init__(self, ID, title, who, ts):

        self.ID = ID
        self.title = title
        self.who = who
        self.ts = ts

    def __hash__(self, *args, **kwargs):

        # Defining hashable interface based on ID so that the object can be
        # used in a set
        return self.ID

    def __eq__(self, other):

        # Required comparison operations for set membership etc
        return hash(self) == hash(other)

    def __neq__(self, other):

        # Required comparison operations for set membership etc
        return not self.__eq__(other)


def create_cache_directory():
    try:

        # Making sure cache directory exists
        cache_directory = os.path.expanduser('~/.cache/deviantart-checker')
        if not os.path.exists(cache_directory):
            os.mkdir(cache_directory)

    except Exception as e:
        raise Exception('Unable to create this program\'s cache '
                        'directory (\'%s\'):\n\n%s\n\n%s\n'
                        % (cache_directory, e, traceback.format_exc()))


def extract_text(html_text, collapse_lines=False):

    # Extract lines of text from HTML tags - this honours linebreaks. Strings
    # is a generator
    text = '\n'.join(bs4.BeautifulSoup(html_text).strings)
    return text if not collapse_lines else text.replace('\n', ' ')


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
    if not 'username' in config or not 'password' in config:
        raise Exception('Please ensure a deviantART username and password is '
                        'configured in \'%s\'' % config_file_path)
    if not 'command_to_run' in config:
        raise Exception('Please ensure command_to_run is configured in \'%s\'' %
                        config_file_path)

    # Ensuring sensible defaults
    # Keep update delay at at least 5 minutes so as not to cause deviantART
    # unnecessary load
    if (not 'update_every_minutes' in config or
            not isinstance(config['update_every_minutes'], numbers.Number) or
            not config['update_every_minutes'] >= 5):
        config['update_every_minutes'] = 5

    # Can't get the indentation to pylint's liking
    # pylint: disable=bad-continuation
    # Validating apply_whitelist_to
    if ((not 'apply_whitelist_to' in config or
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


# Loading config
try:
    load_config()
except Exception as e:  # pylint: disable=broad-except
    print('Unable to load or invalid configuration file:\n\n%s' % e,
          file=sys.stderr)
    sys.exit(1)

# Logging in to deviantART
dA = DeviantArtService(config['username'], config['password'])

# Looping for regular message fetching
while True:

    try:

        # Attempting to log in - errors at this level will be logged and the
        # program will simply wait until the next interval to try again
        if not dA.logged_in:
            dA.login()

        try:

            # Getting the current state of messages
            dA.get_messages()

        # Currently I'll treat all exceptions here as issues with deviantART or
        # an expired login - invalidate the login and report on the issue but
        # reraise waiting for the next loop run to react
        except Exception as e:
            dA.logged_in = False
            raise Exception(e)

        # Working out how the state has changed
        new_comments = dA.get_new(COMMENTS)
        new_replies = dA.get_new(REPLIES)
        new_unread_notes = dA.get_new(UNREAD_NOTES)
        new_deviations = dA.get_new(DEVIATIONS)

        # Setting default change reporting state based on whether there is a
        # notification whitelist in use, and then the particular events affected
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

        # Summarise changes, and when a whitelist is in place, only returning
        # information if it includes something generated from a person of
        # interest
        # Filter is used to remove empty items, list is used to explicitly
        # evaluate immediately
        comments_change_title, comments_change_summary, comments_users = dA.summarise_changes(new_comments, COMMENTS)  # pylint: disable=line-too-long
        if ((notification_whitelist_comments and not set(config['notification_whitelist']).intersection(comments_users)) or  # pylint: disable=line-too-long
                not comments_change_title):
            comments = ''
        else:
            comments = '%s:\n%s' % (comments_change_title,
                                    comments_change_summary)

        replies_change_title, replies_change_summary, replies_users = dA.summarise_changes(new_replies, REPLIES)  # pylint: disable=line-too-long
        if ((notification_whitelist_replies and not set(config['notification_whitelist']).intersection(replies_users)) or  # pylint: disable=line-too-long
                not replies_change_title):
            replies = ''
        else:
            replies = '%s:\n%s' % (replies_change_title,
                                   replies_change_summary)

        unread_notes_change_title, unread_notes_change_summary, unread_notes_users = dA.summarise_changes(new_unread_notes, UNREAD_NOTES)  # pylint: disable=line-too-long
        if ((notification_whitelist_unread_notes and not set(config['notification_whitelist']).intersection(unread_notes_users)) or  # pylint: disable=line-too-long
                not unread_notes_change_title):
            unread_notes = ''
        else:
            unread_notes = '%s:\n%s' % (unread_notes_change_title,
                                        unread_notes_change_summary)

        deviations_change_title, deviations_change_summary, deviations_users = dA.summarise_changes(new_deviations, DEVIATIONS)  # pylint: disable=line-too-long
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

            # Substituting values into command to call in the normal way for
            # the subject since that is essentially fixed - content is not
            # fixed and can contain quotes and speechmarks. I have tried to
            # escape such stuff with shlex.quote, but it can't cope in
            # examples of single quotes, and when a full command is quoted
            # it doesn't execute correctly. Given that I don't want this going
            # through a shell, I should be able to give command parameters
            # straight to the called process without wierd escaping - which is
            # what I am doing here
            command = config['command_to_run'].replace('%s', '[deviantart-checker] ' +  # pylint: disable=line-too-long
                                                       ", ".join(title_bits))
            command_fragments = [fragment.replace('%m', "\n\n".join(content))
                                 for fragment in shlex.split(command)]

            try:

                # Running command without a shell
                subprocess.call(command_fragments)

            except Exception as e:  # pylint: disable=broad-except
                raise Exception('Calling the command to run to notify changes '
                                'failed:\n\n%s\n\n%s\n' % (command, e))

    except Exception as e:  # pylint: disable=broad-except

        # pylint: disable=line-too-long
        # I have decided to just log failures rather than die - this is
        # basically a service, and it is not acceptable for temporary
        # failures to stop the program doing its job - it must simply retry
        # after the usual delay
        # Examples of caught errors:
        # ConnectionError: HTTPSConnectionPool(host='www.deviantart.com', port=443): Max retries exceeded with url: /users/login (Caused by <class 'socket.error'>: [Errno 113] No route to host)
        # (<urllib3.connection.VerifiedHTTPSConnection object at 0x7f7f5f3a5e50>, 'Connection to www.deviantart.com timed out. (connect timeout=60)')
        print('Unhandled error \'%s\'\n\n%s' % (e, traceback.format_exc()),
              file=sys.stderr)

    time.sleep(config['update_every_minutes'] * 60)

