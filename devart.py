'''
Copyright (c) 2014-2016, OmegaPhil - OmegaPhil@startmail.com

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
import os.path
import traceback

import bs4  # Beautiful Soup 4
import requests
import yaml


COMMENTS = 0
REPLIES = 1
UNREAD_NOTES = 2
DEVIATIONS = 3


# Getting new-style class
class AccountState(object):
    '''Maintains the current state of the deviantART account'''


    def __init__(self, state_file_path):
        self.state_file_path = os.path.expanduser(state_file_path)
        self.comments = self.comments_count = self.deviations = None
        self.deviations_count = self.replies = self.replies_count = None
        self.unread_notes = self.unread_notes_count = None
        self.old_comments = self.old_comments_count = None
        self.old_deviations = self.old_deviations_count = None
        self.old_replies = self.old_replies_count = None
        self.old_unread_notes = self.old_unread_notes_count = None

        # Loading previous state
        self.__load_state()


    def __create_cache_directory(self):
        try:
    
            # Making sure cache directory exists
            cache_directory = os.path.dirname(self.state_file_path)
            if not os.path.exists(cache_directory):
                os.mkdir(cache_directory)
    
        except Exception as e:
            raise Exception('Unable to create this program\'s cache '
                            'directory (\'%s\'):\n\n%s\n\n%s\n'
                            % (cache_directory, e, traceback.format_exc()))


    def __load_state(self):

        # Making sure cache directory is present
        self.__create_cache_directory()

        # Loading state if it exists
        if os.path.exists(self.state_file_path):

            # Loading YAML document
            try:
                with io.open(self.state_file_path, 'r') as state_file:
                    state = yaml.load(state_file, yaml.CLoader)
                if state is None:
                    raise Exception('YAML document empty')
            except Exception as e:
                raise Exception('Unable to load state from YAML document '
                                '(\'%s\'):\n\n%s\n\n%s\n'
                                % (self.state_file_path, e,
                                   traceback.format_exc()))

            # Configuring state
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


    def save_state(self):

        # Making sure cache directory is present
        self.__create_cache_directory()

        # Saving state file
        try:
            state = {'comments': self.comments,
                     'commentsCount': self.comments_count,
                     'deviations': self.deviations,
                     'deviationsCount': self.deviations_count,
                     'replies': self.replies,
                     'repliesCount': self.replies_count,
                     'unread_notes': self.unread_notes,
                     'unread_notesCount': self.unread_notes_count}
            with io.open(self.state_file_path, 'w') as state_file:
                yaml.dump(state, state_file, yaml.CDumper)
        except Exception as e:
            raise Exception('Unable to save state into YAML document '
                            '(\'%s\'):\n\n%s\n\n%s\n'
                            % (self.state_file_path, e, traceback.format_exc()))


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
        self.__last_content = None
        self.logged_in = False


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


    def get_messages(self, state):

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
        state.old_comments = state.comments[:]
        state.old_comments_count = state.comments_count
        state.old_replies = state.replies[:]
        state.old_replies_count = state.replies_count
        state.old_unread_notes = state.unread_notes[:]
        state.old_unread_notes_count = state.unread_notes_count
        state.old_deviations = state.deviations[:]
        state.old_deviations_count = state.deviations_count

        # Fetching and saving new message state. Note that replies are
        # basically comments so the class is reused
        state.comments = [Comment(int(hit['msgid']),
                                 extract_text(hit['title'], True),
                                 extract_text(hit['who'], True),
                                 int(hit['ts']), hit['url'],
                                 extract_text(hit['body']))
                         for hit in response['DiFi']['response']['calls'][COMMENTS]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        state.comments_count = response['DiFi']['response']['calls'][COMMENTS]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long
        state.replies = [Comment(int(hit['msgid']),
                                extract_text(hit['title'], True),
                                extract_text(hit['who'], True),
                                int(hit['ts']), hit['url'],
                                extract_text(hit['body']))
                        for hit in response['DiFi']['response']['calls'][REPLIES]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        state.replies_count = response['DiFi']['response']['calls'][REPLIES]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long

        state.unread_notes = [Note(int(hit['msgid']),
                                  extract_text(hit['title'], True),
                                  extract_text(hit['who'], True),
                                  int(hit['ts']))
                             for hit in response['DiFi']['response']['calls'][UNREAD_NOTES]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        state.unread_notes_count = response['DiFi']['response']['calls'][UNREAD_NOTES]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long
        state.deviations = [Deviation(hit['msgid'],
                                     extract_text(hit['title'], True),
                                     int(hit['ts']), hit['url'],
                                     extract_text(hit['username'], True))
                           for hit in response['DiFi']['response']['calls'][DEVIATIONS]['response']['content'][0]['result']['hits']]  # pylint: disable=line-too-long
        state.deviations_count = response['DiFi']['response']['calls'][DEVIATIONS]['response']['content'][0]['result']['count']  # pylint: disable=line-too-long
        state.save_state()


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


    def get_new(self, state, messages_type):

        # Dealing with different message types requested
        if messages_type == COMMENTS:
            return set(state.comments) - set(state.old_comments)
        elif messages_type == REPLIES:
            return set(state.replies) - set(state.old_replies)
        elif messages_type == UNREAD_NOTES:
            return set(state.unread_notes) - set(state.old_unread_notes)
        elif messages_type == DEVIATIONS:
            return set(state.deviations) - set(state.old_deviations)
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


def extract_text(html_text, collapse_lines=False):

    # Extract lines of text from HTML tags - this honours linebreaks. Strings
    # is a generator
    text = '\n'.join(bs4.BeautifulSoup(html_text).strings)
    return text if not collapse_lines else text.replace('\n', ' ')
