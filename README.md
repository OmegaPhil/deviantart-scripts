General
=======

Originally a 'quick' project to make a notifier script trigger command (by
default an email) when certain interesting events happen with my deviantART
account (www.deviantart.com), this is now a small suite of useful scripts to
monitor events and download your own notes/deviation information.  

I don't have a need for further functionality, but as usual if there is enough
demand, I can extend it. Please star this project if you use it so that I know
which projects are most popular and therefore worth working on.


Requirements
============

Tested with (if you get it working on earlier versions please say, all available
in Debian repos):

Python v3.4+  
[Beautiful Soup v4.3.2+](http://www.crummy.com/software/BeautifulSoup/)  
[lxml v3.6.4+](http://lxml.de/) (used as the HTML parser with Beautiful Soup)  
[Requests v2.3.0+](http://python-requests.org)  
[python-YAML v3.11+](http://pyyaml.org/)


Documentation
=============

Credentials Storage
-------------------

The username and password used to access your deviantART account should be
stored in a YAML document at '~/.config/deviantart-scripts/credentials.conf',
e.g.:

    username: Rinoa
    password: Griever

This is a change from v0.5 and earlier where a single script existed so there
wasn't a need to share credentials from a dedicated file.


SQLite Database Inspection
--------------------------

Some scripts now write to SQLite databases - I recommend using [Firefox/
Pale Moon's SQLite Manager addon](https://addons.mozilla.org/en-US/firefox/addon/sqlite-manager/)
to open the database and view the relevant tables (and get all the usual SQL
search functionality etc) - if anyone knows better libre software for this,
please say.


deviantart-checker.py
---------------------

A simple script that takes no arguments and polls deviantART every 5 minutes
(configurable) to determine if any new comments, replies, unread notes and
watched people's deviations have been posted, optionally with a whitelist to
only notify when certain people are involved for certain event types.

To configure, create the '~/.config/deviantart-scripts' directory if it doesn't
exist, and copy/rename 'deviantart-checker-example.conf' to
'deviantart-checker.conf' inside, editing it as needed (see the comments in the
file). Make sure to also create the credentials file mentioned under 'Credentials
Storage' above.

If you follow the sendemail example, when someone replies to a comment you made,
you'll get an email like the following:

    Subject: [deviantart-checker] New Replies

    Message:

    New Replies:

    On <deviation title> by <artist>:

    <user> posted:
    blah blah blah blah

The output has also been tailored for other events and is similar.


deviantart-deviations-downloader.py
-----------------------------------

This script downloads the description and basic details about deviations you
have posted, including the 'gallery folders' that you have placed them in (if
any) to the tbl_deviation, tbl_deviation_folders and tbl_folder tables in an
SQLite database. It isn't intended to download the deviation images themselves
(as I already had backups of them), just the general organisation of your
gallery as a backup.

To configure, create the '~/.config/deviantart-scripts' directory if it doesn't
exist, and copy/rename 'deviantart-deviations-downloader-example.conf' to
'deviantart-deviations-downloader.conf' inside, defining the path to the SQLite
database. Make sure to also create the credentials file mentioned under
'Credentials Storage' above.

This script is a normal 'one-shot' utility rather than a monitoring service,
intended to be ran via anacron as appropriate, that creates/updates (including
deleting from) the given database.

As a UNIX utility, no output is given unless there is a failure, use '--verbose'
for full progress information.


deviantart-notes-downloader.py
------------------------------

This script downloads all notes (sent and received) in all folders associated
with your account to the tbl_note, tbl_note_folders and tbl_folder tables in an
SQLite database.

To configure, create the '~/.config/deviantart-scripts' directory if it doesn't
exist, and copy/rename 'deviantart-notes-downloader-example.conf' to
'deviantart-notes-downloader.conf' inside, defining the path to the SQLite
database. Make sure to also create the credentials file mentioned under
'Credentials Storage' above.

This script is a normal 'one-shot' utility rather than a monitoring service,
intended to be ran via anacron as appropriate, that creates/updates (including
deleting from) the given database.

As a UNIX utility, no output is given unless there is a failure, use '--verbose'
for full progress information.


deviantart-unread-sent-notes-checker.py
---------------------------------------

Similar to the main deviantart-checker script, this script acts as a service
checking your Sent notes folder and alerting you when it notices a note has been
read (presumably by the intended recipient). This is useful when you have lots
of commissions on the go/testing artists, and you want to know who is ignoring
you/not doing due diligence checking their notes etc.

To configure, create the '~/.config/deviantart-scripts' directory if it doesn't
exist, and copy/rename 'deviantart-unread-sent-notes-checker-example.conf' to
'deviantart-unread-sent-notes-checker.conf' inside, editing it as needed (see
the comments in the file). Make sure to also create the credentials file
mentioned under 'Credentials Storage' above.

If you follow the sendemail example, on the next check by the script after the
recipient reads a note, you'll get an email like the following:

    Subject: [deviantart-unread-sent-notes-checker] Freshly-Read Notes

    The following sent notes have now been read:

    '<note title>' sent to <user> on <original date/time of sending>

Obviously the checking is a bit coarse (every 5 minutes by default), so if you
send a note and the recipient reads it within 5 minutes, the script won't
notice (the script first detects unread notes and then their transition to being
read).


Development
===========

Code interacting with deviantART has been moved to the 'devart.py' module - see
the current heavily-commented scripts as examples, I imagine the module can be
reused by others however it has evolved only to do the jobs needed of it (so
certainly isn't a full interface to deviantART nor is it organised in more than
a trivial way). It is unlikely to change outside of new scripts being made, so
should be fairly stable.

The deviantAnywhere Firefox addon
(https://addons.mozilla.org/en-US/firefox/addon/deviantanywhere/) was used as
an example when developing the deviantART service code. 

Thanks goes out to the following sites for documenting part of the DiFi API:
http://botdom.com/documentation/DiFi
https://github.com/danopia/deviantart-difi/wiki


Contact Details
===============

OmegaPhil: OmegaPhil@startmail.com
