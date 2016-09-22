#!/usr/bin/env python3

'''
Version 0.1 2016.09.16
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

import argparse
import io
import os
import os.path
import sqlite3
import sys
import traceback

import yaml

import devart


GPL_NOTICE = '''
Copyright (C) 2016 OmegaPhil
License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
'''


config = {}
con = None

# pylint: disable=global-statement,global-variable-not-assigned


def delete_note_folder_ID(folder_ID):
    '''Delete specified note folder'''

    global con
    con.execute('''
        delete from tbl_note_folders
        where fk_folder_id = :folder_ID;
    ''', {'folder_ID': folder_ID})
    con.execute('''
        delete from tbl_folder
        where id = :folder_ID;
    ''', {'folder_ID': folder_ID})
    con.commit()

    if options.verbose:
        print('Folder ID %s deleted' % folder_ID)


def delete_note_IDs(note_IDs, folder_ID):
    '''Delete specified note IDs'''

    global con

    # Database wrappers don't support substituting in sequences, so just doing
    # it direct
    # Notes can now be mapped to more than one folder, so an outright tbl_note
    # delete needs to ensure there are no remaining mappings
    # This hits up against the usual IN problem - here I'm generating an
    # unnamed parameter string to insert on the IN, and when the parameters are
    # passed I'm making sure to add the folder_ID at the end (the set is
    # converted to a list to make sure that it is impossible for the folder ID
    # to clash with the note IDs, and in the last case, sets can't be multiplied)
    unnamed_params = ','.join(['?' for note_ID in note_IDs])
    note_IDs_params_1 = list(note_IDs) + [folder_ID]
    note_IDs_params_2 = list(note_IDs) * 2
    con.execute('''
        delete from tbl_note_folders
        where fk_note_id in (%s)
            and fk_folder_id = ?;
    ''' % unnamed_params, note_IDs_params_1)
    con.commit()
    con.execute('''
        delete from tbl_note
        where id in (%(unnamed_params)s) and id not in (
            select fk_note_id
            from tbl_note_folders
            where fk_note_id in (%(unnamed_params)s)
        )
    ''' % {'unnamed_params': unnamed_params}, note_IDs_params_2)
    con.commit()

    if options.verbose:
        print('Note IDs deleted: %s' % note_IDs)


def get_current_note_folder_IDs():
    '''Fetch the IDs associated with note folders recorded in the database'''

    global con

    folder_IDs_result = con.execute('''
        select id
        from tbl_folder
    ''').fetchall()

    # Remove silly tuples
    return [folder_ID[0] for folder_ID in folder_IDs_result]


def get_note_ids_in_folder(folder_ID):
    '''Fetch all note IDs associated with a particular folder'''

    global con

    note_IDs = con.execute('''
        select n.id
        from tbl_note n
        inner join tbl_note_folders nf on n.id = nf.fk_note_id 
            and nf.fk_folder_id = :folder_ID
    ''', {'folder_ID': folder_ID}).fetchall()

    # Converting to a set without silly tuples, and making sure not to return
    # None
    if note_IDs is None:
        return set()
    else:
        return {ID[0] for ID in note_IDs}


def get_last_note_id(folder_ID):
    '''Fetch the ID of the newest note in a folder'''

    # pylint: disable=redefined-outer-name

    global con

    last_note_ID = con.execute('''
        select n.id
        from tbl_note n
        inner join tbl_note_folders nf on n.id = nf.fk_note_id 
            and nf.fk_folder_id = :folder_ID
        order by n.id desc 
        limit 1
    ''', {'folder_ID': folder_ID}).fetchone()

    # Make sure not to return None
    if last_note_ID is None:
        return 0
    else:
        return int(last_note_ID[0])


def get_note_folder_notes_count(folder_ID):
    '''Get a count of all notes in a folder'''

    # I dont think there is a need to ensure the folder exists
    global con
    return con.execute('''
        select count(1)
        from tbl_note n
        inner join tbl_note_folders nf on n.id = nf.fk_note_id 
            and nf.fk_folder_id = :folder_ID
    ''', {'folder_ID': folder_ID}).fetchone()[0]


def load_config():
    '''Load config'''

    global config

    # Loading configuration if it exists
    config_directory = os.path.expanduser('~/.config/deviantart-notes-downloader')
    config_file_path = os.path.join(config_directory, 'deviantart-notes-downloader.conf')
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
    if 'database_path' not in config:
        raise Exception('Please ensure database_path is configured in \'%s\'' %
                        config_file_path)
    if 'ignored_folders' not in config:
        config['ignored_folders'] = []


def prepare_database(database_path):
    '''Prepare database'''

    dir_path = os.path.dirname(database_path)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    # sqlite will create a non-existent database, but naturally I need to set up
    # the schema in that case. Making sure not to shadow passed con
    global con
    con = sqlite3.connect(database_path)
    con.executescript('''
        -- Enabling referential integrity
        pragma foreign_keys = on;
        
        /* Ensuring correct tables are present. Lookup tables will be so small
         * that I dont think its worth adding indexes for text fields
         * Folder IDs are actually text...
         * One note can be in more than one folder - so a folder is essentially
         * a view, e.g. Inbox and Starred - hence the extra mapping table */
        create table if not exists tbl_note ( 
            id integer primary key not null,
            title text not null,
            sender text not null,
            timestamp integer not null,
            text text not null);
        create table if not exists tbl_folder ( 
            id text primary key not null,
            title text not null);
        create table if not exists tbl_note_folders (
            id integer primary key not null,
            fk_note_id integer not null references tbl_note,
            fk_folder_id integer not null references tbl_folder
        );
        create index if not exists fk_note_id_fk_folder_id on tbl_note_folders(fk_note_id, fk_folder_id);
        create index if not exists sender on tbl_note(sender);
    ''')
    con.commit()


def record_note(note):
    '''Record note in database'''

    # pylint: disable=redefined-outer-name

    global con

    # At this point the associated folder is already guaranteed created, so just
    # inserting in - however since one note can appear in many folders (e.g.
    # Inbox and Starred), insert or ignore is used
    con.execute('''
        insert or ignore into tbl_note(id, title, sender, timestamp, text)
        values(:id, :title, :sender, :timestamp, :text);
        ''',
        {'id': note.ID, 'title': note.title, 'sender': note.who,
         'timestamp': note.ts, 'text':note.text})
    con.execute('''
        insert into tbl_note_folders(fk_note_id, fk_folder_id)
        values(:id, :folder_id);
        ''',
        {'id': note.ID, 'folder_id': note.folder_ID})
    con.commit()

    if options.verbose:
        print('New note recorded, ID: \'%s\', title: \'%s\', sender: \'%s\', '
              'timestamp: \'%s\', folder ID: \'%s\''
              % (note.ID, note.title, note.who, note.ts, note.folder_ID))


def record_note_folder(note_folder):
    '''Record note folder in database'''

    # pylint: disable=redefined-outer-name

    global con

    # Detecting renames at the same time as creating new folders
    current_folder_name = con.execute('''
        select title
        from tbl_folder
        where id = :folder_ID
    ''', {'folder_ID': note_folder.ID}).fetchone()
    if current_folder_name is None:

        con.execute('''insert into tbl_folder(id, title)
                    values(:id, :title)''',
                    {'id': note_folder.ID, 'title': note_folder.title})
        con.commit()

        print('Note folder \'%s\' recorded' % note_folder.title)
    else:

        # Removing stupid tuple
        current_folder_name = current_folder_name[0]

        if current_folder_name != note_folder.title:

            con.execute('''
                update tbl_folder
                set title = :title
                where id = :id
            ''', {'id': note_folder.ID, 'title': note_folder.title})
            con.commit()

            if options.verbose:
                print('Note folder ID \'%s\' renamed to \'%s\''
                      % (note_folder.ID, note_folder.title))

# Configuring and parsing passed options
parser = argparse.ArgumentParser()
parser.add_argument('-f', '--fsck', dest='fsck', help='force compare note IDs in'
' local and remote folders to delete/fetch as appropriate', action='store_true',
default=False)
parser.add_argument('--verbose', dest='verbose', help='verbose output of '
'script activities', action='store_true', default=False)
options = parser.parse_args()

try:
    load_config()
except Exception as e:  # pylint: disable=broad-except
    print('Unable to load or invalid configuration file:\n\n%s' % e,
          file=sys.stderr)
    sys.exit(1)

# Ensuring destination database is ready
try:
    prepare_database(config['database_path'])
except Exception as e:  # pylint: disable=broad-except
    print('Unable to prepare and open the \'%s\' SQLite database for use:\n\n%s\n'
          % (config['database_path'], e), file=sys.stderr)
    sys.exit(1)

try:
    dA = devart.DeviantArtService(config['username'], config['password'])
    dA.login()
except Exception as e:  # pylint: disable=broad-except
    print('Unable to log in to DeviantArt:\n\n%s\n' % e, file=sys.stderr)
    con.close()
    sys.exit(1)

# Obtaining list of folders to work through
try:
    note_folders = dA.get_note_folders()
except Exception as e:  # pylint: disable=broad-except
    print('Unable to fetch available note folders:\n\n%s\n' % e,
          file=sys.stderr)
    con.close()
    sys.exit(1)

# Removing any note_folders the user wants to ignore (better than manually
# skipping them in each loop)
if config['ignored_folders']:
    note_folders = [folder for folder in note_folders
                    if folder not in config['ignored_folders']]

# Only run the main loop if not running in fsck mode (this is redundant
# otherwise)
if not options.fsck:
    for note_folder in note_folders:  # pylint: disable=redefined-outer-name

        if options.verbose:
            print('Processing note folder \'%s\'...' % note_folder.title)

        # Ensuring note folder is recorded in the database (also deals with renames)
        record_note_folder(note_folder)

        # Obtaining the last/latest note ID recorded for this folder
        last_note_ID = get_last_note_id(note_folder.ID)
        if options.verbose:
            print('Last note ID for this folder: %s' % last_note_ID)

        # Fetching notes
        note_offset = 0
        last_fetched_note_detected = False
        while True:

            if options.verbose:
                print('Fetching notes at offset %d...' % note_offset)
            notes = dA.get_notes_in_folder(note_folder.ID, note_offset)
            if options.verbose:
                print('%d notes returned, processing...' % len(notes))

            for note in notes:

                # Notes are returned newest first, ID increases over time
                # If the latest note has already been recorded, skip to next folder
                if note.ID <= last_note_ID:
                    last_fetched_note_detected = True
                    break

                record_note(note)

            # Breaking if notes have been fetched
            # If less than 25 notes are returned, its the last page of notes (of
            # course doesn't detect the situation where exactly 25 notes are on the
            # last page)
            if last_fetched_note_detected or len(notes) < 25:
                if options.verbose:
                    print('Last note in folder processed')
                break

            # Looping
            note_offset += 25

# Detecting deleted folders - the direction of the set delete is important
# Fsck mode should still delete and rename folders
if options.verbose:
    print('Checking for folders to delete...')
db_note_folders = set(get_current_note_folder_IDs())
da_note_folders = set([note_folder.ID for note_folder in note_folders])
deleted_folders = db_note_folders - da_note_folders
for deleted_folder_ID in deleted_folders:
    delete_note_folder_ID(deleted_folder_ID)

# At this point the latest notes from all folders should be fetched, along with
# old folders killed off. Some notes may have been deleted from a folder since
# an earlier run of the program - since the script doesn't scan every folder in
# its entirety on each run, it doesn't have a proper collection of the note IDs
# that should exist - so can't tell exactly when some notes have been deleted
# and others added (e.g. old notes being moved between folders).
# Given that most notes should come in the Inbox or be moved into a folder, and
# deletions will be rare, it makes sense to stick with the initial 'new notes
# fetching', then confirm that the notes count deviantART reports in a folder
# is mirrored locally now. If a number is different, the folder must be fully
# audited. This won't detect 5 old notes being deleted in a folder along with
# 5 old notes being moved in from another folder, but it should be good enough
# for normal use. Would be nice if deviantART could offer a single call to get
# all note IDs from a folder...

# Now that everything is supposedly synced, checking for note count
# discrepancies, or in fsck mode, indiscriminately checking everything
if options.verbose:
    if options.fsck:
        print('Force-checking note folders...')
    else:
        print('Checking for note count discrepancies...')
for note_folder in note_folders:
    local_notes_count = get_note_folder_notes_count(note_folder.ID)
    if options.fsck or note_folder.site_note_count != local_notes_count:

        # Fetching sets of IDs on deviantART and the local database - for large
        # folders this will result in multiple DiFi calls
        if options.verbose:
            if options.fsck:
                print('Checking folder \'%s\' - remote count: %s, local count: '
                      '%s' % (note_folder.title, note_folder.site_note_count,
                              local_notes_count))
            else:
                print('Discrepancy detected for folder \'%s\' - remote count: '
                      '%s, local count: %s'
                      % (note_folder.title, note_folder.site_note_count,
                         local_notes_count))
        dA_note_ids = dA.get_note_ids_in_folder(note_folder.ID)
        local_note_ids = get_note_ids_in_folder(note_folder.ID)

        # Notes to delete
        note_ids_to_delete = local_note_ids - dA_note_ids
        if note_ids_to_delete:
            if options.verbose:
                print('Deleting note IDs %s...' % note_ids_to_delete)
            delete_note_IDs(note_ids_to_delete, note_folder.ID)

        # Notes to fetch
        note_ids_to_fetch = dA_note_ids - local_note_ids
        if note_ids_to_fetch:
            if options.verbose:
                print('Fetching note IDs %s...' % note_ids_to_fetch)
            for note_ID in note_ids_to_fetch:
                note = dA.get_note_in_folder(note_folder.ID, note_ID)
                record_note(note)

con.close()

if options.verbose:
    print('Finished')
