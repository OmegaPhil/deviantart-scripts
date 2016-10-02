#!/usr/bin/env python3

'''
Version 0.1 2016.10.02
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


config = {}
con = None

# pylint: disable=global-statement,global-variable-not-assigned


def delete_deviation(deviation):

    global con

    # Reusing this code rather than duplicating - also cleans out folders that
    # are now empty
    record_removed_deviation_folder_mappings(deviation, deviation.folders)

    # Deleting deviation
    con.execute('''
        delete from tbl_deviation_folders
        where fk_deviation_id = :id
    ''', {'id': deviation.ID})
    con.execute('''
        delete from tbl_deviation
        where id = :id
    ''', {'id': deviation.ID})
    con.commit()

    if options.verbose:
        print('Deviation \'%s\' deleted' % deviation.title)


def get_all_deviations():
    '''Fetch all known deviations'''

    global con

    deviations = con.execute('''
        select id, title, url, username, timestamp, description
        from tbl_deviation
    ''').fetchall()

    return [devart.Deviation(record[0], record[1], record[2], record[3],
                             record[4], record[5]) for record in deviations]


def get_last_deviation_id():
    '''Fetch the ID of the newest deviation'''

    global con

    last_deviation_ID = con.execute('''
        select id
        from tbl_deviation
        order by id desc 
        limit 1
    ''').fetchone()

    # Make sure not to return None
    if last_deviation_ID is None:
        return 0
    else:
        return int(last_deviation_ID[0])


def get_deviation_folders(deviation_ID):
    '''Return a list of deviation folders associated with the passed deviation'''

    global con
    recordset = con.execute('''
        select f.id, f.title, f.description, f.url
        from tbl_deviation d
        inner join tbl_deviation_folders df on d.id = df.fk_deviation_id
            and d.id = :id
        inner join tbl_folder f on df.fk_folder_id = f.id
    ''', {'id': deviation_ID}).fetchall()

    return [devart.DeviationFolder(record[0], record[1], record[2], record[3])
            for record in recordset]


def load_config():
    '''Load config'''

    global config

    # Loading configuration if it exists. Credentials has been split out into
    # its own file so that it can be shared amongst various scripts
    config_directory = os.path.expanduser('~/.config/deviantart-scripts')
    config_file_path = os.path.join(config_directory, 'deviantart-deviations-downloader.conf')
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
                            % (config_file_path, credentials_file_path, e,
                               traceback.format_exc()))

    # Ensuring required settings exist
    if 'username' not in config or 'password' not in config:
        raise Exception('Please ensure a deviantART username and password is '
                        'configured in \'%s\'' % credentials_file_path)
    if 'database_path' not in config:
        raise Exception('Please ensure database_path is configured in \'%s\'' %
                        config_file_path)


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
         * Deviation folder descriptions should be blank when they have no 
         * content, not NULL */
        create table if not exists tbl_deviation ( 
            id integer primary key not null,
            title text not null,
            url text not null,
            username text not null,
            timestamp integer not null,
            description text not null);
        create table if not exists tbl_folder ( 
            id text primary key not null,
            title text not null,
            description text not null,
            url text not null);
        create table if not exists tbl_deviation_folders (
            id integer primary key not null,
            fk_deviation_id integer not null references tbl_deviation,
            fk_folder_id integer not null references tbl_folder
        );
        create unique index if not exists fk_note_id_fk_folder_id on tbl_deviation_folders(fk_deviation_id, fk_folder_id);
        create index if not exists fk_note_id_fk_folder_id on tbl_deviation_folders(fk_deviation_id, fk_folder_id);
        create index if not exists title on tbl_deviation(title);
        create index if not exists title on tbl_folder(title);
    ''')
    con.commit()


def record_deviation(deviation):
    '''Record deviation in database'''

    # pylint: disable=redefined-outer-name

    global con

    # At this point the associated folders are already guaranteed created, so
    # just inserting in
    con.execute('''
        insert into tbl_deviation(id, title, url, username, timestamp,
        description)
        values(:id, :title, :url, :username, :timestamp, :description);
        ''',
        {'id': deviation.ID, 'title': deviation.title, 'url': deviation.URL,
         'username': deviation.username, 'timestamp': deviation.ts,
         'description': deviation.description})

    # Recording all folder mappings
    for deviation_folder in deviation.folders:
        con.execute('''
            insert into tbl_deviation_folders(fk_deviation_id, fk_folder_id)
            values(:id, :folder_id);
            ''',
            {'id': deviation.ID, 'folder_id': deviation_folder.ID})
    con.commit()

    # All custom classes now have a string method, so printing deviation.folders
    # will be useful
    if options.verbose:
        print('New deviation recorded, ID: \'%s\', title: \'%s\', URL: \'%s\', '
              'username: \'%s\', timestamp: \'%s\', description: \'%s\', '
              'folders: \'%s\''
              % (deviation.ID, deviation.title, deviation.URL,
                 deviation.username, deviation.ts, deviation.description,
                 deviation.folders))


def record_deviation_folders(deviation_folders):
    '''Make sure deviation folders passed are recorded in the database'''

    # pylint: disable=redefined-outer-name

    global con

    for deviation_folder in deviation_folders:

        # Recording deviation folder if its not already in the database -
        # separating this out in order to get proper feedback for verbose mode
        folder_exists = con.execute('''
            select 1
            from tbl_folder
            where id = :folder_id
        ''', {'folder_id': deviation_folder.ID}).fetchone()
        if folder_exists is None:

            con.execute('''
                insert into tbl_folder(id, title, description, url)
                values(:id, :title, :description, :url)
            ''', {'id': deviation_folder.ID, 'title': deviation_folder.title,
                  'description': deviation_folder.description,
                  'url': deviation_folder.URL})

            print('Deviation folder \'%s\' recorded' % deviation_folder.title)

    con.commit()


def record_new_deviation_folder_mappings(deviation, deviation_folders):
    '''Associate deviation with new folders in the database'''

    # Full deviation passed in to get at its title

    # pylint: disable=redefined-outer-name

    global con

    for deviation_folder in deviation_folders:
        con.execute('''
            insert into tbl_deviation_folders(fk_deviation_id, fk_folder_id)
            values(:id, :folder_id)
        ''', {'id': deviation.ID, 'folder_id': deviation_folder.ID})
    con.commit()

    if deviation_folders and options.verbose:
        print('Deviation \'%s\' is associated with new deviation folders \'%s\''
          % (deviation.title, deviation_folders))


def record_removed_deviation_folder_mappings(deviation, deviation_folders):
    '''Remove association of deviation with given folders in the database'''

    # Full deviation passed in to get at its title

    # pylint: disable=redefined-outer-name

    global con

    for deviation_folder in deviation_folders:

        # Should only be a few of these, so not going to bother doing IN, and it
        # needs to be separated in a loop to deal with the folder cleanup
        con.execute('''
            delete from tbl_deviation_folders
            where fk_deviation_id = :id
                and fk_folder_id = :folder_id
        ''', {'id': deviation.ID, 'folder_id': deviation_folder.ID})

        # Cleaning up folders with no deviations
        deviations_mapped_count = con.execute('''
            select count(1)
            from tbl_deviation_folders
            where fk_folder_id = :folder_id
        ''', {'folder_id': deviation_folder.ID}).fetchone()
        if deviations_mapped_count is None:
            con.execute('''
                delete from tbl_folder
                where id = :folder_id
            ''', {'folder_id': deviation_folder.ID})
    con.commit()

    if deviation_folders and options.verbose:
        print('Deviation \'%s\' is no longer associated with the deviation '
        'folders \'%s\'' % (deviation.title, deviation_folders))


# Configuring and parsing passed options
parser = argparse.ArgumentParser()
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

# Fetching basic deviation information for all deviations in one go upfront
deviation_offset = 0
deviations = []
while True:

    if options.verbose:
        print('Fetching deviations at offset %s...' % deviation_offset)

    # Obtaining list of deviations to work through (120/fetch)
    try:
        deviations_fetched = dA.get_all_deviations(config['username'],
                                                   deviation_offset)
        deviations += deviations_fetched
    except Exception as e:  # pylint: disable=broad-except
        print('Unable to fetch all deviations from offset %s:\n\n%s\n'
              % (deviation_offset, e), file=sys.stderr)
        con.close()
        sys.exit(1)

    if options.verbose:
        print('%d deviations fetched' % len(deviations_fetched))

    # Detecting end of deviations list
    if len(deviations_fetched) < 120:
        break

    # Looping
    deviation_offset += 120

# Obtaining the last fetched deviation ID from the prior run
last_deviation_id = get_last_deviation_id()
if options.verbose:
    print('Last deviation ID: %s' % last_deviation_id)

recorded_deviation_folders = []
for deviation in deviations:

    # Deviations are returned newest first, ID increases over time
    if deviation.ID > last_deviation_id:

        # New deviation detected - fetch the real detail, combine with folder
        # information only available via the gallery
        full_deviation = dA.get_deviation(deviation.URL)
        full_deviation.folders = deviation.folders

        # Making sure folders are recorded, caching to reduce pointless lookups/
        # insert or ignore attempts. Should only be a few folders so a list is
        # fine
        for deviation_folder in deviation.folders:
            if deviation_folder not in recorded_deviation_folders:
                record_deviation_folders([deviation_folder])
                recorded_deviation_folders.append(deviation_folder)

        # Recording the deviation
        record_deviation(full_deviation)
    else:

        # Known deviation detected - obtaining associated folders
        current_deviation_folders = get_deviation_folders(deviation.ID)

        # Determining differences and recording in database (
        # record_removed_deviation_folder_mappings deals with deleting unused
        # folders)
        new_deviation_folders = (set(deviation.folders) -
                                 set(current_deviation_folders))
        unknown_deviation_folders = (set(new_deviation_folders) -
                                     set(recorded_deviation_folders))
        record_deviation_folders(unknown_deviation_folders)
        record_new_deviation_folder_mappings(deviation, new_deviation_folders)
        deleted_deviation_folders = (set(current_deviation_folders)
                                     - set(deviation.folders))
        record_removed_deviation_folder_mappings(deviation,
                                                 deleted_deviation_folders)

# Detecting and dealing with deleted deviations
known_deviation_ids = set(get_all_deviations())
deleted_deviations = known_deviation_ids - set(deviations)
for deleted_deviation in deleted_deviations:
    delete_deviation(deleted_deviation)

con.close()

if options.verbose:
    print('Finished')
