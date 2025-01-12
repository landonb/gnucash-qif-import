GnuCash QIF Import
==================

[GnuCash][GnuCash] Python helper script to import transactions from [QIF][QIF] text files into GnuCash .gnucash file (or into MySQL).

Main use case for myself was automating the import of QIF files generated by [GnuCash Mobile][GnuCash Mobile] Android app into my desktop GnuCash application.

See also [my blog post "Synchronizing GnuCash mobile with GnuCash desktop"][my blog post].


Prerequisites
--------------

* Python 2.7+
* GnuCash 2.4+
* GnuCash Python Bindings
* MySQL Server (optional, to store Gnucash data into MySQL)
* MTP tools (optional, to import from MTP device)

Getting Started
---------------

For Ubuntu 13.04, 14.04:

    sudo apt-get install gnucash python-gnucash
    ./import.py -v -f examples/accounts.gnucash examples/expenses.qif

For Ubuntu 13.04, 14.04 (MySQL):

    sudo apt-get install gnucash python-gnucash
    sudo apt-get install libdbd-mysql
    mysql -u $USERNAME -p$PASSWORD -h $HOSTNAME
    mysql> create database accounts;
    mysql> use accounts;
    mysql> source examples/accounts.sql
    ./import.py -v -f mysql://$USERNAME:$PASSWORD@$HOSTNAME/accounts examples/expenses.qif

The above command should log two "Adding transaction for account.." lines and will add the expenses from examples/expenses.qif to the accounts.gnucash file.
Open accounts.gnucash (or the equivalent database in case of MySQL) with GnuCash before and after executing the above command line to see the difference.

The Python script will assume "EUR" as default currency (QIF files do not specify any currency). Use the `--currency` command line flag to change this.

How to import from MTP device (Android phone)
---------------------------------------------

The import.py script also supports directly importing QIF files from devices supporting [MTP][MTP], e.g. Android phones.
This is handy if you use [GnuCash Mobile][GnuCash Mobile] and want to synchronize (importing previously saved QIF files) when connecting your phone via USB.
You need the "mtp-tools" command line programs to use this feature:

    sudo apt-get install mtp-tools

To import all files ending with ".qif" from your MTP device (connected via USB) into your "my-accounts" GnuCash file:

    ./import.py -v -f ~/my-accounts.gnucash mtp:.*.qif

You can use the `--dry-run` option to do a safe trial run if you use a file based GnuCash file. The dry run does not work on DB backends (i.e. all data is always written)
In order to be able to safely repeat the above command without getting a bunch of duplicate transactions (and to speed up the stupidly slow MTP access),
the import.py script remembers the imported file names in `~/.gnucash-qif-import-cache.json`.


[my blog post]:   http://srcco.de/posts/synchronizing-gnucash-mobile-with-gnucash-desktop.html
[GnuCash]:        http://www.gnucash.org
[QIF]:            http://en.wikipedia.org/wiki/Quicken_Interchange_Format
[MTP]:            http://en.wikipedia.org/wiki/Media_Transfer_Protocol
[GnuCash Mobile]: https://play.google.com/store/apps/details?id=org.gnucash.android&hl=en
