#!/usr/bin/env python3

import hail as hl
import os

def main():
    await hl.init_service(default_reference='GRCh38', billing_project=os.getenv('HAIL_BILLING_PROJECT'))
    hl.import_table('test.csv')

if __name__ == '__main__':
    main()
