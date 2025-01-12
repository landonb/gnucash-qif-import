#!/usr/bin/env python3
# vim:tw=0:ts=4:sw=4:et:norl:ft=python

'''
GnuCash Python helper script to import transactions from QIF text files into GnuCash's own file format.

https://github.com/hjacobs/gnucash-qif-import
'''

import argparse
import datetime
import json
import logging
import os
import re
import subprocess
import sys                                  # required to identify the errors for error catching and terminating the script
import traceback                            # required to output error trace
import tempfile
import qif
from decimal import Decimal

# CXREF: `gnucash` docs:
#   https://code.gnucash.org/docs/MAINT/modules.html
# CXREF: Related project with *piecash* support:
#   https://github.com/sanzoghenzo/piecash-qif-import
from gnucash import Account, GncNumeric, Session, Split, Transaction

MTP_SCHEME = 'mtp:'


def lookup_account_by_path(root, path, book):
    acc = root.lookup_by_name(path[0])
    if acc is None or acc.get_instance() is None:
        # Don't croak, e.g.,:
        #   raise Exception('Account path {} not found'.format(':'.join(path)))
        # But assume user wants `mkdir -p`-esque side-effects.
        is_placeholder = len(path) > 1

        logging.info(f"Adding account: {path[0]} (is{is_placeholder and ' not'} placeholder)")

        acc = Account(book)
        acc.SetName(path[0])
        acc.SetType(root.GetType())
        acc.SetPlaceholder(is_placeholder)
        acc.SetCommodity(root.GetCommodity())

        root.append_child(acc)

    if len(path) > 1:
        return lookup_account_by_path(acc, path[1:], book)
    return acc


def lookup_account(root, name, book=None):
    path = name.split(':')
    return lookup_account_by_path(root, path, book)


def add_transaction(book, item, currency):
    logging.info('Adding transaction for account "%s" (%s %s)..', item.account, item.split_amount,
                 currency.get_mnemonic())
    root = book.get_root_account()
    acc = lookup_account(root, item.account, book)

    # If Split not specified, default to source account values.
    # - As inspired by 2 users' forks I found while auditing changes since
    #   the root project hasn't been updated since 2017 (and Python 2).
    #   - See:
    #       https://github.com/sbluhm/gnucash-qif-import/commit/7db3112
    #       https://github.com/stephanritscher/gnucash-qif-import/commit/2c5a6fa
    # WATCH/2021-03-13: I'm blindly incorporating changes without actually testing,
    # so I'm not sure the best approach here, but I think it's stephanritscher's,
    # who uses an Imbalance account (whereas sbluhm uses item.category).
    #   split_category = item.split_category or item.category
    split_category = item.split_category or 'Imbalance-{}'.format(currency)
    split_amount = item.split_amount if item.split_amount is not None else item.amount
    split_memo = item.split_memo if item.split_memo is not None else item.memo

    # HINT/2021-03-13: If you need to check the books for duplicates first, see:
    #   https://github.com/psyipm/gnucash-qif-import/commit/587b5b5

    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(currency)
    # 2021-03-13: The original GnuCash 2 code:
    #  tx.SetDateEnteredTS(datetime.datetime.now())
    #  tx.SetDatePostedTS(item.date)
    # The equivalent GnuCash 3 code:
    tx.SetDateEnteredSecs(datetime.datetime.now())
    tx.SetDatePostedSecs(item.date)
    # WATCH/2021-03-13 19:27: But per sbluhm, the GNC 3 calls are incorrect.
    # - See:
    #     https://github.com/sbluhm/gnucash-qif-import/commit/0ccb1e9
    # - Says:
    #     Had to change the GnuCash 3 function tx.SetDatePostedSecs to
    #     tx.SetDate. SetDatePostedSecs seems to contain a bug where the time
    #     is not interpreted properly (wrong time zone adaptions. For the same
    #     reason, tx.SetDateEnteredSecs was removed. Especially, as this time
    #     stamp is set automatically to the same value, when creating a new
    #     entry.
    # - Changes code to:
    #  # SetDatePostedSecs contains a bug by wrongly adapting to timezones so reverting to this function.
    #  tx.SetDate(item.date.day, item.date.month, item.date.year)

    # "Deal with new field mapping of GnuCash for Android"
    #   https://github.com/markusj/gnucash-qif-import/commit/f1c4558
    if item.payee is None:    
        tx.SetDescription(item.memo)
    else:
        tx.SetDescription(item.payee)
        tx.SetNotes(item.memo)

    # WATCH/2021-03-13: If you need to process multiple splits, see markusj:
    # - *Add suport for split transactions*
    #     https://github.com/markusj/gnucash-qif-import/commit/ec068cb
    #     https://github.com/markusj/gnucash-qif-import/commit/ecfe025
    #     https://github.com/markusj/gnucash-qif-import/commit/33da80b

    s1 = Split(book)
    s1.SetParent(tx)
    s1.SetAccount(acc)
    amount = int(Decimal(split_amount.replace(',', '.')) * currency.get_fraction())
    s1.SetValue(GncNumeric(amount, currency.get_fraction()))
    s1.SetAmount(GncNumeric(amount, currency.get_fraction()))

    acc2 = lookup_account(root, split.category, book)
    s2 = Split(book)
    s2.SetParent(tx)
    s2.SetAccount(acc2)
    s2.SetValue(GncNumeric(amount * -1, currency.get_fraction()))
    s2.SetAmount(GncNumeric(amount * -1, currency.get_fraction()))
    s2.SetMemo(split_memo)

    tx.CommitEdit()


def read_entries_from_mtp_file(file_id, filename):
    with tempfile.NamedTemporaryFile(suffix=filename) as fd:
        subprocess.check_call(['mtp-getfile', file_id, fd.name])
        entries_from_qif = qif.parse_qif(fd)
    logging.debug('Read %s entries from %s', len(entries_from_qif), filename)
    return entries_from_qif


def get_mtp_files():
    '''list all files on MTP device and return a tuple (file_id, filename) for each file'''

    # using mtp-tools instead of pymtp because I could not get pymtp to work (always got segmentation fault!)
    out = subprocess.check_output('mtp-files 2>&1', shell=True)
    last_file_id = None
    for line in out.splitlines():
        cols = line.strip().split(':', 1)
        if len(cols) == 2:
            key, val = cols
            if key.lower() == 'file id':
                last_file_id = val.strip()
            elif key.lower() == 'filename':
                filename = val.strip()
                yield (last_file_id, filename)


def read_entries_from_mtp(pattern, imported):
    entries = []
    regex = re.compile(pattern)
    for file_id, filename in get_mtp_files():
        if regex.match(filename):
            logging.debug('Found matching file on MTP device: "%s" (ID: %s)', filename, file_id)
            if filename in imported:
                logging.info('Skipping %s (already imported)', filename)
            else:
                entries.extend(read_entries_from_mtp_file(file_id, filename))
                imported.add(filename)
    return entries


def read_entries(fn, imported):
    logging.debug('Reading %s..', fn)
    if fn.startswith(MTP_SCHEME):
        items = read_entries_from_mtp(fn[len(MTP_SCHEME):], imported)
    else:
        base = os.path.basename(fn)
        if base in imported:
            logging.info('Skipping %s (already imported)', base)
            return []
        with open(fn) as fd:
            items = qif.parse_qif(fd)
        imported.add(fn)
    logging.debug('Read %s items from %s', len(items), fn)
    return items


def write_transactions_to_gnucash(gnucash_file, currency, all_items, dry_run=False, date_from=None):
    logging.debug('Opening GnuCash file %s..', gnucash_file)
    session = Session(gnucash_file)
    try:                                            # Close the GnuCash file if an error occured
        book = session.book
        commod_tab = book.get_table()
        currency = commod_tab.lookup('ISO4217', currency)

        if date_from:
            date_from = datetime.datetime.strptime(date_from, '%Y-%m-%d')

        imported_items = set()
        for item in all_items:
            if date_from and item.date < date_from:
                logging.info('Skipping entry %s (%s)', item.date.strftime('%Y-%m-%d'), item.split_amount)
                continue
            if item.as_tuple() in imported_items:
                logging.info('Skipping entry %s (%s) --- already imported!', item.date.strftime('%Y-%m-%d'),
                             item.split_amount)
                continue
            add_transaction(book, item, currency)
            imported_items.add(item.as_tuple())
    except:                                         # Output error and quit
        session.end()
        e = sys.exc_info()
        logging.error('Something did not work:')
        logging.error(e[0])
        traceback.print_exception(*e)
        sys.exit()
            
    if dry_run:
        logging.debug('** DRY-RUN **')
    else:
        logging.debug('Saving GnuCash file..')
        session.save()
    session.end()


def main(args):
    if args.verbose:
        lvl = logging.DEBUG
    elif args.quiet:
        lvl = logging.WARN
    else:
        lvl = logging.INFO

    logging.basicConfig(level=lvl)

    imported_cache = os.path.expanduser('~/.gnucash-qif-import-cache.json')
    if os.path.exists(imported_cache):
        with open(imported_cache) as fd:
            imported = set(json.load(fd))
    else:
        imported = set()

    all_items = []
    for fn in args.file:
        all_items.extend(read_entries(fn, imported))

    if all_items:
        write_transactions_to_gnucash(args.gnucash_file, args.currency, all_items, dry_run=args.dry_run,
                                      date_from=args.date_from)

    if not args.dry_run:
        with open(imported_cache, 'w') as fd:
            json.dump(list(imported), fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', help='Verbose (debug) logging', action='store_true')
    parser.add_argument('-q', '--quiet', help='Silent mode, only log warnings', action='store_true')
    parser.add_argument('--dry-run', help='Noop, do not write anything', action='store_true')
    parser.add_argument('--date-from', help='Only import transaction >= date (YYYY-MM-DD)')
    parser.add_argument('-c', '--currency', metavar='ISOCODE', help='Currency ISO code (default: EUR)', default='EUR')
    parser.add_argument('-f', '--gnucash-file', help='Gnucash data file')
    parser.add_argument('file', nargs='+',
                        help='Input QIF file(s), can also be "mtp:<PATTERN>" to import from MTP device')

    args = parser.parse_args()
    main(args)

