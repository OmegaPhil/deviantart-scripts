'''
Copyright (c) 2014-2017, OmegaPhil - OmegaPhil@startmail.com

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
import datetime
import io
import os.path
import re
import traceback
import urllib.parse

import bs4  # Beautiful Soup 4
import requests
import yaml


COMMENTS = 0
REPLIES = 1
UNREAD_NOTES = 2
DEVIATIONS = 3


# pylint: disable=too-many-lines


# Getting new-style class
class AccountState(object):
    '''Maintains the current state of the deviantART account'''

    # pylint: disable=too-many-instance-attributes,too-few-public-methods

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
        '''Save internal state to the configured state file'''

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
        if not validate_difi_response(response, 0):
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


    def get_all_deviations(self, username, deviation_offset):
        '''Fetch the IDs, titles, links and folders associated with all
        deviations via the gallery page -> All link, with the offset allowing
        you to page through the results (max 120 are returned by deviantART).
        Full deviation detail should be fetched separately per deviation when
        you need it'''

        # pylint: disable=too-many-locals

        try:

            # Determining gallery URL
            gallery_url = 'https://%s.deviantart.com/gallery/' % username

            # The catpath parameter is the 'all' selector
            params = {'catpath': '/', 'offset': deviation_offset}

            # I don't yet know of any DiFi way to do this that actually works,
            # so just fetching the pages as usual
            self.__r = self.__s.get(gallery_url, params=params, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to load all deviations gallery page from '
                            'offset \'%s\':\n\n%s\n\n%s\n'
                            % (deviation_offset, e, traceback.format_exc()))

        # Parsing page
        self.__last_content = bs4.BeautifulSoup(self.__r.content, 'lxml')

        # Locating the main stream div (it turns out that classes like 'tt-a'
        # are also used outside of the deviations listing)
        div_deviations = (self.__last_content.
                          select_one('div#gmi-ResourceStream'))
        if div_deviations is None:
            raise Exception('Unable to locate the main div containing the '
                            'deviations in the gallery page - HTML:\n\n%s\n'
                            % self.__last_content)

        known_deviation_folders = {}
        deviations = []
        for deviation_span in div_deviations.select('span.thumb'):

            # Fetching the deviation link and validating
            if 'href' not in deviation_span.attrs:
                raise Exception('Unable to fetch the href from the following '
                                'deviation span:\n\n%s\n\nProblem occurred '
                                'while fetching all deviations from '
                                'offset \'%s\''
                                % deviation_span, deviation_offset)

            deviation_URL = deviation_span.attrs['href']

            # Fetching deviation ID
            if 'data-deviationid' not in deviation_span.attrs:
                raise Exception('Unable to fetch the deviation ID from the '
                                'following deviation span:\n\n%s\n\nProblem '
                                'occurred while fetching all deviations from '
                                'offset \'%s\''
                                % deviation_span, deviation_offset)

            deviation_ID = deviation_span.attrs['data-deviationid']

            # Fetching deviation title and validating
            title_span = deviation_span.select_one('span.title')
            if title_span is None:
                raise Exception('Unable to locate the title span for deviation '
                                'ID \'%s\' from the following deviation span:\n'
                                '\n%s\n\nProblem occurred while fetching all '
                                'deviations from offset \'%s\''
                                % (deviation_ID, deviation_span,
                                   deviation_offset))

            deviation_title = title_span.text

            # Fetching deviation folders involved and validating (being
            # associated with no folders is perfectly acceptable)
            # 16.02.17: dA appears to have redone the HTML here such that folders
            # are no longer available via deviation records in the main gallery
            # bit (they aren't available in the deviation's page either)... so
            # this effectively kills off folder recording for now
            folder_link_tags = deviation_span.select('span.gallections a')
            deviation_folders = []
            for folder_link_tag in folder_link_tags:
                folder_URL = folder_link_tag.attrs['href']
                folder_title = folder_link_tag.text

                # Caching deviation folders so that you don't have to fetch the
                # folder page every time to get the description
                if folder_title in known_deviation_folders:

                    # Folder has already been fetched - using current data
                    deviation_folders.append(known_deviation_folders[folder_title])

                else:

                    # Folder is new - fetching full information from its page (
                    # description isn't available otherwise)
                    deviation_folder = self.get_deviation_folder(folder_URL)
                    deviation_folders.append(deviation_folder)

                    # Adding to cache
                    known_deviation_folders[folder_title] = deviation_folder

            # All deviation detail fetched, constructing
            deviations.append(Deviation(deviation_ID, deviation_title,
                                        deviation_URL, username,
                                        folders=deviation_folders))

        return deviations


    def get_deviation(self, deviation_URL):
        '''Fetch all deviation information bar folders for the specified
        deviation URL (folders are only available via the gallery page)'''

        try:

            # I don't yet know of any DiFi way to do this that actually works,
            # so just fetching the pages as usual
            self.__r = self.__s.get(deviation_URL, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to load the deviation page from the '
                            'specified URL \'%s\':\n\n%s\n\n%s\n'
                            % (deviation_URL, e, traceback.format_exc()))

        # Parsing page
        self.__last_content = bs4.BeautifulSoup(self.__r.content, 'lxml')

        # Determining deviation ID
        try:
            deviation_ID = deviation_url_to_id(deviation_URL)
        except Exception as e:
            raise Exception('Unable to extract deviation ID from link \'%s\''
                            % deviation_URL)

        # Fetching the title link tag and validating
        title_link_tag = self.__last_content.select_one('h1 a')
        if title_link_tag is None:
            raise Exception('Unable to fetch the title link tag from the '
                            'deviation link \'%s\', HTML:n\n%s\n'
                            % (deviation_URL, self.__last_content))
        deviation_title = title_link_tag.text

        # Fetching the username link tag and validating
        username_link_tag = self.__last_content.select_one('a.username')
        if username_link_tag is None:
            raise Exception('Unable to fetch the username link tag from the '
                            'deviation link \'%s\', HTML:n\n%s\n'
                            % (deviation_URL, self.__last_content))
        username = username_link_tag.text

        # Fetching timestamp span and validating
        timestamp_span_tag = (self.__last_content
                              .select_one('div.dev-metainfo-details dd span'))
        if timestamp_span_tag is None:
            raise Exception('Unable to fetch the timestamp span tag from the '
                            'deviation link \'%s\', HTML:n\n%s\n'
                            % (deviation_URL, self.__last_content))
        if 'ts' not in timestamp_span_tag.attrs:
            raise Exception('Unable to fetch the timestamp from the '
                            'deviation link \'%s\' - span tag:n\n%s\n'
                            % (deviation_URL, timestamp_span_tag))
        timestamp = timestamp_span_tag.attrs['ts']

        # Fetching the description div tag and validating - some deviations
        # genuinely don't have a description - in this case the div.text tag
        # is not present
        description_div_tag = self.__last_content.select_one('div.text')
        if description_div_tag is None:
            deviation_description = ''
        else:

            # Turn deviantART post into sensible text
            deviation_description = deviantart_post_to_text(description_div_tag)

        # Can't get at folder information here, seems only the gallery pages
        # show this

        # All deviation detail fetched, constructing
        return Deviation(deviation_ID, deviation_title, deviation_URL, username,
                         timestamp, deviation_description)


    def get_deviation_folder(self, deviation_folder_URL):
        '''Fetch deviation folder information from its gallery page'''

        try:

            # I don't yet know of any DiFi way to do this that actually works,
            # so just fetching the pages as usual
            self.__r = self.__s.get(deviation_folder_URL, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to load the deviation folder page from the '
                            'specified URL \'%s\':\n\n%s\n\n%s\n'
                            % (deviation_folder_URL, e, traceback.format_exc()))

        # Parsing page
        self.__last_content = bs4.BeautifulSoup(self.__r.content, 'lxml')

        # Determining deviation folder ID
        match = re.match(r'^.+/([0-9]+)/.+$', deviation_folder_URL)
        if match is None:
            raise Exception('Unable to extract deviation folder ID from link '
                            '\'%s\'' % deviation_folder_URL)
        deviation_folder_ID = int(match.groups()[0])

        # Fetching folder title span and validating
        folder_title_span = self.__last_content.select_one('span.folder-title')
        if folder_title_span is None:
            raise Exception('Unable to fetch the deviation folder title span '
                            'tag from the deviation folder link \'%s\', HTML:'
                            'n\n%s\n'
                            % (deviation_folder_URL, self.__last_content))
        deviation_folder_title = folder_title_span.text

        # Fetching folder description div and validating - when a folder has
        # no description, the div still appears but with no text, which is fine
        folder_description_div = (self.__last_content
                                  .select_one('div.description.text'))
        if folder_description_div is None:
            raise Exception('Unable to fetch the deviation folder description '
                            'div tag from the deviation folder link \'%s\', '
                            'HTML:n\n%s\n'
                            % (deviation_folder_URL, self.__last_content))
        deviation_folder_description = folder_description_div.text

        return DeviationFolder(deviation_folder_ID, deviation_folder_title,
                               deviation_folder_description,
                               deviation_folder_URL)


    def get_messages(self, state):
        '''Fetch new messages from deviantART'''

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

        # Making sure difi response and all contained calls are valid - remember
        # that the range is generating 0-3 and stopping at 4 (so it is correctly
        # generating a 4-call range)
        response = self.__r.json()
        if not validate_difi_response(response, range(4)):
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

        # Special processing needs to be done for notes to fetch the text
        state.unread_notes = []
        for hit in response['DiFi']['response']['calls'][UNREAD_NOTES]['response']['content'][0]['result']['hits']:  # pylint: disable=line-too-long
            note_ID = int(hit['msgid'])
            note_title = extract_text(hit['title'], True)
            try:
                state.unread_notes.append(self.get_note_in_folder('unread',
                                                                  note_ID))
            except Exception as e:
                raise Exception('Unable to get text of unread note ID \'%s\', '
                                'title \'%s\':\n\n%s\n\n%s\n'
                                % (note_ID, note_title, e,
                                   traceback.format_exc()))
        state.unread_notes_count = len(state.unread_notes)

        # Deviation IDs come through in a mangled form - the msgid has the
        # the structure '<number>:<deviation ID>', no idea what the number is
        state.deviations = [Deviation(hit['msgid'].split(':')[1],
                                     extract_text(hit['title'], True),
                                     hit['url'],
                                     extract_text(hit['username'], True),
                                     int(hit['ts']))
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


    def get_note_folders(self):
        '''Obtain list of note folders from deviantART'''

        # DiFi doesn't appear to provide a way to get a list of folders, so just
        # fetching and parsing the notes page
        try:
            notifications_url = 'http://www.deviantart.com/notifications/notes'
            self.__r = self.__s.get(notifications_url, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to load deviantART notes page:\n\n%s\n\n%s'
                            '\n' % (e, traceback.format_exc()))

        # Parsing page
        self.__last_content = bs4.BeautifulSoup(self.__r.content, 'lxml')

        # Determining list of note folders
        note_folders = []
        for folder_link in self.__last_content.select('a.folder-link'):

            # Validating link data
            if 'data-folderid' not in folder_link.attrs:
                raise Exception('Unable to obtain the folder ID from link tag '
                                '\'%s\' - failed to generate a list of notes '
                                'folders in the get_notes_folders call!'
                                % folder_link)
            if 'title' not in folder_link.attrs:
                raise Exception('Unable to obtain the folder title from link tag'
                                '\'%s\' - failed to generate a list of notes '
                                'folders in the get_notes_folders call!'
                                % folder_link)

            # 'rel' is actually the count of contained notes, used as a
            # sanity check . Note that even though there is only one rel attribute,
            # Beautiful Soup returns a list?? Also need to remove thousands
            # separator etc
            if 'rel' not in folder_link.attrs:
                raise Exception('Unable to obtain the folder notes count from '
                                'link tag \'%s\' - failed to generate a list of '
                                'notes folders in the get_notes_folders call!'
                                % folder_link)
            notes_count = int(folder_link.attrs['rel'][0].replace(',', ''))

            note_folder = NoteFolder(folder_link.attrs['data-folderid'],
                                           folder_link.attrs['title'])
            note_folder.site_note_count = notes_count
            note_folders.append(note_folder)

        return note_folders


    def get_note_in_folder(self, folder_ID, note_ID):
        '''Fetch a note from a folder'''

        # pylint: disable=too-many-branches,too-many-locals,too-many-statements

        # Dealing with special folder_IDs - remember not to update the folder_ID
        # variable so that you don't permanently corrupt it
        prepared_folder_ID = format_note_folder_id(folder_ID)

        try:

            # The 'ui' field in the form is actually the 'userinfo' cookie -
            # its not directly usable via the cookie value, have to urldecode.
            # This is on top of having the correct login cookies...
            data = {'c[]': ['"Notes","display_note",[%s,%s]'
                           % (prepared_folder_ID, note_ID)],
                     'ui': urllib.parse.unquote(self.__s.cookies['userinfo']),
                     't': 'json'}
            self.__r = self.__s.post(self.__difi_url, data=data, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to fetch note ID \'%s\' from folder ID '
                            '\'%s\':\n\n%s\n\n%s\n'
                            % (note_ID, folder_ID, e,
                               traceback.format_exc()))

        # Making sure difi response and all contained calls are valid
        response = self.__r.json()
        if not validate_difi_response(response, range(1)):
            raise Exception('The DiFi page request to fetch note ID \'%s\' from'
                            ' folder ID \'%s\' succeeded but the DiFi request '
                            'failed:\n\n%s\n'
                            % (note_ID, folder_ID, response))

        # Actual note data is returned in HTML
        html_data = bs4.BeautifulSoup(response['DiFi']['response']['calls'][0]['response']['content']['body'], 'lxml')  # pylint: disable=line-too-long

        # Fetching note title and validating
        note_span = html_data.select_one('span.mcb-title')
        if not note_span:
            raise Exception('Unable to obtain note title from the following note'
                            ' HTML:\n\n%s\n\nProblem occurred while fetching '
                            'note ID \'%s\' from folder ID \'%s\''
                            % (html_data.text, note_ID, folder_ID))
        note_title = note_span.text

        # Fetching sender details and validating
        sender_span = html_data.select_one('span.mcb-from')
        if not sender_span:
            raise Exception('Unable to obtain note sender from the following '
                            'note HTML:\n\n%s\n\nProblem occurred while fetching'
                            ' note ID \'%s\' from folder ID \'%s\''
                            % (html_data.text, note_ID, folder_ID))
        if 'username' not in sender_span.attrs:
            raise Exception('Unable to obtain note sender username from the '
                            'following note HTML:\n\n%s\n\nProblem occurred '
                            'while fetching note ID \'%s\' from folder ID \'%s\''
                            % (html_data.text, note_ID, folder_ID))
        note_sender = sender_span.attrs['username']

        # Fetching recipient details and validating (this has meaning in the
        # sent folder)
        recipient_span = html_data.select_one('span.mcb-to')
        if not recipient_span:
            raise Exception('Unable to obtain note recipient (recipient span) '
                            'from the following note HTML:\n\n%s\n\nProblem '
                            'occurred while fetching note ID \'%s\' from folder'
                            ' ID \'%s\'' % (html_data.text, note_ID, folder_ID))
        recipient_link = recipient_span.select_one('a.username')
        if not recipient_link:

            # pylint: disable=line-too-long
            # Banned users have their username displayed differently, e.g.:
            # '<span class="mcb-to">to <span class="username-with-symbol"><span class="banned username">CrimsonColt7</span><span class="user-symbol banned" data-gruser-type="banned" data-quicktip-text="Banned or Deactivated/Closed Account" data-show-tooltip="1"></span></span></span>'
            recipient_link = recipient_span.select_one('span.username')
            if not recipient_link:
                raise Exception('Unable to obtain note recipient (recipient '
                                'link) from the following note HTML:\n\n%s\n\n'
                                'Problem occurred while fetching note ID \'%s\''
                                'from folder ID \'%s\''
                                % (html_data.text, note_ID, folder_ID))
        note_recipient = recipient_link.text

        # Fetching timestamp and validating
        timestamp_span = html_data.select_one('span.mcb-ts')
        if not timestamp_span:
            raise Exception('Unable to obtain timestamp span from the '
                            'following note HTML:\n\n%s\n\nProblem occurred'
                            ' while fetching note ID \'%s\' from folder ID \'%s\''
                            % (html_data.text, note_ID, folder_ID))
        if 'title' not in timestamp_span.attrs:
            raise Exception('Unable to obtain timestamp \'title\' from the '
                            'timestamp span from the following note HTML:'
                            '\n\n%s\n\nProblem occurred while fetching note ID '
                            '\'%s\' from folder ID \'%s\''
                            % (html_data.text, note_ID, folder_ID))
        note_timestamp = timestamp_span.attrs['title']

        # If the timestamp includes 'ago', its not the proper timestamp - after
        # notes get ~1 week old, deviantART switches the proper timestamp into
        # the tag text rather than the title attribute
        if 'ago' in note_timestamp:
            note_timestamp = timestamp_span.text

        try:

            # Converting the deviantART datetime string into a proper UNIX
            # timestamp
            # Example: 'Jun 9, 2014, 11:08:28 PM'
            note_timestamp = datetime.datetime.strptime(note_timestamp,
                                                '%b %d, %Y, %I:%M:%S %p')
            note_timestamp = note_timestamp.timestamp()

        except ValueError as e:
            raise Exception('Unable to parse timestamp \'%s\' from note ID '
                            '\'%s\' while fetching note from folder ID \'%s\':'
                            '\n\n%s\n\n%s\n'
                            % (note_timestamp, note_ID, folder_ID, e,
                               traceback.format_exc()))

        # Fetching note HTML and validating
        div_wraptext = html_data.select_one('.mcb-body.wrap-text')
        if not div_wraptext:
            raise Exception('Unable to parse note text from the following note '
                            'HTML:\n\n%s\n\nProblem occurred while '
                            'fetching note ID \'%s\' from from folder ID \'%s\''
                            % (html_data, note_ID, folder_ID))

        # Turn deviantART post into sensible text
        note_text = deviantart_post_to_text(div_wraptext)

        # Finally instantiating the note
        note = Note(note_ID, note_title, note_sender, note_recipient,
                    note_timestamp, note_text, folder_ID)

        return note


    def get_note_ids_in_folder(self, folder_ID):
        '''Fetch all note IDs in a set from specified folder (one DiFi call per
        25 notes) - used to audit note IDs stored in the database'''

        # Dealing with special folder_IDs
        folder_ID = format_note_folder_id(folder_ID)

        note_ids = set()
        offset = 0
        while True:

            notes_detected = False

            try:

                # The 'ui' field in the form is actually the 'userinfo' cookie -
                # its not directly usable via the cookie value, have to urldecode.
                # This is on top of having the correct login cookies...
                data = {'c[]': ['"Notes","display_folder",[%s,%s,0]'
                               % (folder_ID, offset)],
                         'ui': urllib.parse.unquote(self.__s.cookies['userinfo']),
                         't': 'json'}
                self.__r = self.__s.post(self.__difi_url, data=data, timeout=60)
                self.__r.raise_for_status()

            except Exception as e:
                raise Exception('Unable to fetch note IDs from offset \'%s\' '
                                'from folder ID \'%s\':\n\n%s\n\n%s\n'
                                % (offset, folder_ID, e,
                                   traceback.format_exc()))

            # Making sure difi response and all contained calls are valid
            response = self.__r.json()
            if not validate_difi_response(response, range(1)):
                raise Exception('The DiFi page request to fetch note IDs from '
                                'offset \'%s\' from folder ID \'%s\' succeeded '
                                'but the DiFi request failed:\n\n%s\n'
                                % (offset, folder_ID, response))

            # Actual note data is returned in HTML
            html_data = bs4.BeautifulSoup(response['DiFi']['response']['calls'][0]['response']['content']['body'], 'lxml')  # pylint: disable=line-too-long

            for listitem_tag in html_data.select('li.note'):

                notes_detected = True

                # Fetching note details and validating
                note_details = listitem_tag.select_one('.note-details')
                if not note_details:
                    raise Exception('Unable to parse note details from the '
                                    'following note HTML:\n\n%s\n\nProblem '
                                    'occurred while fetching note IDs from '
                                    'offset \'%s\' from folder ID \'%s\''
                                    % (listitem_tag, offset, folder_ID))

                # Fetching note ID and validating
                note_details_link = note_details.select_one('span > a')
                if not note_details_link:
                    raise Exception('Unable to parse note details link from the '
                                    ' following note HTML:\n\n%s\n\nProblem '
                                    'occurred while fetching note IDs from '
                                    'offset \'%s\' from folder ID \'%s\''
                                    % (listitem_tag, offset, folder_ID))
                if 'data-noteid' not in note_details_link.attrs:
                    raise Exception('Unable to obtain note ID from note details '
                                    'link from the following note HTML:\n\n%s'
                                    '\n\nProblem occurred while fetching notes '
                                    'from offset \'%s\' from folder ID \'%s\''
                                    % (listitem_tag, offset, folder_ID))

                # Collecting obtained note_ID - note that these IDs are supposed
                # to be ints, affects set comparisons etc (int !=str)
                note_ids.add(int(note_details_link.attrs['data-noteid']))

            # Breaking if no notes were returned
            if not notes_detected:
                break

            # Looping - notes are available in 25-note pages
            offset += 25

        return note_ids


    def get_notes_in_folder(self, folder_ID, note_offset):
        '''Fetch desired notes from specified folder, with the offset allowing
        you to page through the folder (max 25 notes are returned by
        deviantART), note data is fetched in separate DiFi calls'''

        # Dealing with special folder_IDs - remember not to update the folder_ID
        # variable so that you don't permanently corrupt it
        prepared_folder_ID = format_note_folder_id(folder_ID)

        try:

            # The 'ui' field in the form is actually the 'userinfo' cookie -
            # its not directly usable via the cookie value, have to urldecode.
            # This is on top of having the correct login cookies...
            data = {'c[]': ['"Notes","display_folder",[%s,%s,0]'
                           % (prepared_folder_ID, note_offset)],
                     'ui': urllib.parse.unquote(self.__s.cookies['userinfo']),
                     't': 'json'}
            self.__r = self.__s.post(self.__difi_url, data=data, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to fetch notes from offset \'%s\' from '
                            'folder ID \'%s\':\n\n%s\n\n%s\n'
                            % (note_offset, folder_ID, e,
                               traceback.format_exc()))

        # Making sure difi response and all contained calls are valid
        response = self.__r.json()
        if not validate_difi_response(response, range(1)):
            raise Exception('The DiFi page request to fetch notes from offset '
                            '\'%s\' from folder ID \'%s\' succeeded but the DiFi'
                            ' request failed:\n\n%s\n'
                            % (note_offset, folder_ID, response))

        # Actual note data is returned in HTML - note that this is actually a
        # preview (corrupted URLs and linebreaks), so notes must still be fetched
        # individually
        html_data = bs4.BeautifulSoup(response['DiFi']['response']['calls'][0]['response']['content']['body'], 'lxml')  # pylint: disable=line-too-long

        notes = []
        for listitem_tag in html_data.select('li.note'):

            # Fetching note details and validating
            note_details = listitem_tag.select_one('.note-details')
            if not note_details:
                raise Exception('Unable to parse note details from the following'
                                ' note HTML:\n\n%s\n\nProblem occurred while '
                                'fetching notes from offset \'%s\' from folder '
                                'ID \'%s\'' % (listitem_tag, note_offset,
                                               folder_ID))

            # Fetching note ID and validating
            note_details_link = note_details.select_one('span > a')
            if not note_details_link:
                raise Exception('Unable to parse note details link from the '
                                ' following note HTML:\n\n%s\n\nProblem occurred'
                                ' while fetching notes from offset \'%s\' from '
                                'folder ID \'%s\''
                                % (listitem_tag, note_offset, folder_ID))
            if 'data-noteid' not in note_details_link.attrs:
                raise Exception('Unable to obtain note ID from note details link'
                                ' from the following note HTML:\n\n%s\n\nProblem'
                                ' occurred while fetching notes from offset '
                                '\'%s\' from folder ID \'%s\''
                                % (listitem_tag, note_offset, folder_ID))
            note_ID = note_details_link.attrs['data-noteid']

            # Fetching the note text and metadata separately - it turns out that
            # at this level you really do just get a preview, which has corrupted
            # links and collapsed newlines
            notes.append(self.get_note_in_folder(folder_ID, note_ID))

        return notes


    def get_unread_sent_notes(self):
        '''Fetch up to 25 sent notes (one page's worth) that have not been read
        by the recipient'''

        try:

            # The 'ui' field in the form is actually the 'userinfo' cookie -
            # its not directly usable via the cookie value, have to urldecode.
            # This is on top of having the correct login cookies...
            data = {'c[]': ['"Notes","display_folder",[%s,%s,0]' % ('2', 0)],
                     'ui': urllib.parse.unquote(self.__s.cookies['userinfo']),
                     't': 'json'}
            self.__r = self.__s.post(self.__difi_url, data=data, timeout=60)
            self.__r.raise_for_status()

        except Exception as e:
            raise Exception('Unable to fetch sent notes from offset 0:\n\n'
                            '%s\n\n%s\n' % (e, traceback.format_exc()))

        # Making sure difi response and all contained calls are valid
        response = self.__r.json()
        if not validate_difi_response(response, range(1)):
            raise Exception('The DiFi page request to fetch notes from offset 0'
                            ' from folder ID \'%s\' succeeded but the DiFi'
                            ' request failed:\n\n%s\n' % ('2', response))

        # Actual note data is returned in HTML
        html_data = bs4.BeautifulSoup(response['DiFi']['response']['calls'][0]['response']['content']['body'], 'lxml')  # pylint: disable=line-too-long

        # Luckily we can select precisely the unread notes here - the
        # class-based CSS selector here isn't a hierarchy but defines a list
        # item with both the note and unread classes
        notes = []
        for listitem_tag in html_data.select('li.note.unread'):

            # Fetching note details and validating
            note_details = listitem_tag.select_one('.note-details')
            if not note_details:
                raise Exception('Unable to parse note details from the following'
                                ' note HTML:\n\n%s\n\nProblem occurred while '
                                'fetching unsent notes from offset 0'
                                % listitem_tag)

            # Fetching note ID and validating
            note_details_link = note_details.select_one('span > a')
            if not note_details_link:
                raise Exception('Unable to parse note details link from the '
                                ' following note HTML:\n\n%s\n\nProblem occurred'
                                ' while fetching unsent notes from offset 0'
                                % listitem_tag)
            if 'data-noteid' not in note_details_link.attrs:
                raise Exception('Unable to obtain note ID from note details link'
                                ' from the following note HTML:\n\n%s\n\nProblem'
                                ' occurred while fetching unsent notes from '
                                'offset 0' % listitem_tag)
            note_ID = note_details_link.attrs['data-noteid']

            # Fetching the note text and metadata separately - it turns out that
            # at this level you really do just get a preview, which has corrupted
            # links and collapsed newlines
            notes.append(self.get_note_in_folder('2', note_ID))

        return notes


    def last_page_content(self):
        '''The last normal page loaded by requests'''

        return self.__last_content


    def login(self):
        '''Login to deviantART'''

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
        self.__last_content = bs4.BeautifulSoup(self.__r.content, 'lxml')

        # Locating login form
        login_form = self.__last_content.find('form', id='login')
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
        # print('validate_token: %s\nvalidate_key: %s'% (validate_token,
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
        self.__last_content = bs4.BeautifulSoup(self.__r.content, 'lxml')


class Comment:
    '''Represents a comment or reply (the latter is basically a comment. Replies
    are called 'Feedback Messages' on deviantART'''

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
    '''Represents a deviation'''

    # pylint: disable=too-few-public-methods,too-many-arguments

    # Optional parameters to allow a for a more sparse Deviation object when
    # representing all deviations through fetching the All gallery
    # (see get_all_deviations) - fetching ts and description here when its not
    # needed would be serious bloat (120 extra calls in just one page fetch of
    # a gallery for data that wouldn't be used)
    # Folders is a list of DeviationFolders that represent the deviation/gallery
    # folders the deviation is part of
    def __init__(self, ID, title, URL, username, ts=None, description=None,
                 folders=None):

        # Making sure ID is an int if it is passed in as a string (this is
        # relied on for comparisons, the ID increments over time)
        if isinstance(ID, str):
            if not ID.isdigit():
                raise Exception('Unable to instantiate deviation with non '
                                'integer ID \'%s\'!' % ID)
            ID = int(ID)

        self.ID = ID
        self.title = title
        self.URL = URL
        self.username = username
        self.ts = ts
        self.description = description

        # Python can't cope with a list as a default value, so working around
        # this here
        if folders is None:
            self.folders = []
        else:
            self.folders = folders

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

    def __repr__(self):

        # Return user-friendly title
        return 'Deviation (\'%s\')' % self.title


class DeviationFolder:
    '''Represents a folder that a deviation is attached to in a user gallery'''

    # pylint: disable=too-few-public-methods

    def __init__(self, ID, title, description, URL):

        # Making sure ID is an int if it is passed in as a string (this is
        # relied on for comparisons, the ID increments over time)
        if isinstance(ID, str):
            if not ID.isdigit():
                raise Exception('Unable to instantiate deviation folder with '
                                'non integer ID \'%s\'!' % ID)
            ID = int(ID)

        self.ID = ID
        self.title = title
        self.description = description
        self.URL = URL

    def __hash__(self, *args, **kwargs):

        # Defining hashable interface based on ID
        return self.ID

    def __eq__(self, other):

        # Required comparison operations for set membership etc
        return hash(self) == hash(other)

    def __neq__(self, other):

        # Required comparison operations for set membership etc
        return not self.__eq__(other)

    def __repr__(self):

        # Return user-friendly title
        return 'DeviationFolder (\'%s\')' % self.title


class Note:
    '''Represents a note'''

    # pylint: disable=too-few-public-methods,too-many-arguments

    # Notes have normally been populated via the MessageCenter view, which
    # doesn't include the note text - however this is now available
    # Rather than a Note, this is more a 'note view', since one Note can be in
    # more than one NoteFolder (e.g. Inbox and Starred) - however I want to keep
    # things simple currently and stick with one folder ID per Note object
    def __init__(self, ID, title, sender, recipient, ts, text, folder_ID):

        # Making sure ID is an int if it is passed in as a string (this is
        # relied on for comparisons, the ID increments over time)
        if isinstance(ID, str):
            if not ID.isdigit():
                raise Exception('Unable to instantiate note with non integer ID'
                                ' \'%s\'!' % ID)
            ID = int(ID)

        self.ID = ID
        self.title = title
        self.sender = sender
        self.recipient = recipient
        self.ts = ts
        self.text = text
        self.folder_ID = folder_ID


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

    def __repr__(self):

        # Return user-friendly title
        return 'Note (\'%s\')' % self.title


class NoteFolder:
    '''Represents a default or custom folder for notes (in reality a view on
    applicable notes in deviantART'''

    # pylint: disable=too-few-public-methods

    def __init__(self, ID, title):

        # ID is actually text, can be actual strings like 'unread'
        self.ID = ID
        self.title = title

        # Useful stat to use as a heuristic for unnoticed change detection
        self.site_note_count = None

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

    def __repr__(self):

        # Return user-friendly title
        return 'NoteFolder (\'%s\')' % self.title


def extract_text(html_text, collapse_lines=False):
    '''Extract lines of text from HTML tags - this honours linebreaks'''

    # Strings is a generator
    # Cope with html_text when it is already a BeautifulSoup tag
    if isinstance(html_text, str):
        html_text = bs4.BeautifulSoup(html_text, 'lxml')
    text = '\n'.join(html_text.strings)
    return text if not collapse_lines else text.replace('\n', ' ')


def deviantart_post_to_text(div_tag):
    '''Turn deviantART post contained in the passed div tag into sensible text'''

    # Turn links in the div to text links without the deviantART redirector
    for link_tag in div_tag.select('a'):
        if 'http://' in link_tag.attrs['href']:
            link_tag.string = link_tag.attrs['href'].replace(
                        'http://www.deviantart.com/users/outgoing?', '')
        else:
            link_tag.string = link_tag.attrs['href'].replace(
                        'https://www.deviantart.com/users/outgoing?', '')
        link_tag.unwrap()

    # Replace out linebreaks with newlines to ensure they get honoured
    for linebreak in div_tag.select('br'):
        linebreak.replace_with('\n')

    # TODO: In the future I should textify things like smilies etc
    return div_tag.text.strip()


def deviation_url_to_id(deviation_URL):
    '''Extract a deviation ID from a deviation URL'''

    match = re.match(r'^.+-([0-9]+)$', deviation_URL)
    if match is None:
        raise Exception('Unable to extract deviation ID from link \'%s\''
                        % deviation_URL)
    return int(match.groups()[0])


def format_note_folder_id(folder_ID):
    '''Dealing with special folder_IDs that are genuinely strings (e.g.
    unread') - these need to be speechmark-delimited for deviantART not to
    raise a bullshit error about the class name'''

    if not folder_ID.isdigit():
        return '"%s"' % folder_ID
    else:
        return folder_ID


def get_new(state, messages_type):
    '''Determining what new messages have been fetched'''

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


def validate_difi_response(response, call_numbers):
    '''Determining if the overall DiFi page call and all associated function
    calls were successful or not'''

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
