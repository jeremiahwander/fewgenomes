#!/usr/bin/env python

"""
Convert matrix table to a sites-only VCF.
Essentially a verbatim copy of: hail-ukbb-200k-callset:mt_to_vcf.py
"""

import logging
import click
import hail as hl
from gnomad.utils.vcf import adjust_vcf_incompatible_types
from gnomad.utils.sparse_mt import default_compute_info
from joint_calling import _version
from joint_calling.utils import get_validation_callback, init_hail, file_exists
from joint_calling import utils

logger = logging.getLogger('mt_2_vcf')
logging.basicConfig(
    format='%(asctime)s (%(name)s %(lineno)s): %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S %p',
)
logger.setLevel(logging.INFO)


@click.command()
@click.version_option(_version.__version__)
@click.option(
    '--mt',
    'mt_path',
    required=True,
    callback=get_validation_callback(ext='mt', must_exist=True),
    help='path to the input MatrixTable',
)
@click.option(
    '-o',
    'output_path',
    required=True,
)
@click.option(
    '--local-tmp-dir',
    'local_tmp_dir',
    help='local directory for temporary files and Hail logs (must be local).',
)
@click.option(
    '--overwrite/--reuse',
    'overwrite',
    is_flag=True,
    help='if an intermediate or a final file exists, skip running the code '
    'that generates it.',
)
@click.option(
    '--hail-billing',
    'hail_billing',
    help='Hail billing account ID.',
)
@click.option(
    '--n-partitions',
    'n_partitions',
    type=click.INT,
    default=5000,
    help='Desired base number of partitions for the output matrix table',
)
def main(
    mt_path: str,
    output_path: str,
    local_tmp_dir: str,
    overwrite: bool,
    hail_billing: str,  # pylint: disable=unused-argument
    n_partitions: int,
):  # pylint: disable=missing-function-docstring
    init_hail('variant_qc', local_tmp_dir)

    logger.info(f'Loading matrix table from "{mt_path}"')
    mt = hl.read_matrix_table(mt_path)
    export_sites_only_vcf(mt=mt, output_path=output_path, n_partitions=n_partitions)


def export_sites_only_vcf(
    mt: hl.MatrixTable, output_path: str, n_partitions: int = 5000
):
    """
    Take initial matrix table, convert to sites-only matrix table, then export to vcf
    """
    logger.info('Converting matrix table to sites-only matrix table')
    ht = mt_to_sites_only_ht(mt, n_partitions)
    logger.info(
        f"Exporting sites-only VCF to '{output_path}' to run in the VQSR pipeline"
    )
    hl.export_vcf(ht, output_path)
    logger.info('Successfully exported sites-only VCF')

    return output_path


def mt_to_sites_only_ht(mt: hl.MatrixTable, n_partitions: int) -> hl.Table:
    """
    Convert matrix table (mt) into sites-only VCF-ready table (ht)
    :param mt: multi-sample matrix table
    :param n_partitions: number of partitions for the output table
    :return: hl.Table
    """

    mt = _filter_rows_and_add_tags(mt)
    ht = _create_info_ht(mt, n_partitions=n_partitions)
    ht = adjust_vcf_incompatible_types(ht)
    return ht


def _filter_rows_and_add_tags(mt: hl.MatrixTable) -> hl.MatrixTable:
    mt = hl.experimental.densify(mt)

    # Filter to only non-reference sites.
    # An examle of a variant with hl.len(mt.alleles) > 1 BUT NOT
    # hl.agg.any(mt.LGT.is_non_ref()) is a variant that spans a deletion,
    # which was however filtered out, so the LGT was set to NA, however the site
    # was preserved to account for the presence of that spanning deletion.
    # locus   alleles    LGT
    # chr1:1 ["GCT","G"] 0/1
    # chr1:3 ["T","*"]   NA
    mt = mt.filter_rows((hl.len(mt.alleles) > 1) & (hl.agg.any(mt.GT.is_non_ref())))

    # annotate site level DP as site_dp onto the mt rows to avoid name collision
    mt = mt.annotate_rows(site_dp=hl.agg.sum(mt.DP))

    # Add AN tag as ANS
    return mt.annotate_rows(ANS=hl.agg.count_where(hl.is_defined(mt.GT)) * 2)


def _create_info_ht(mt: hl.MatrixTable, n_partitions: int) -> hl.Table:
    """Create info table from vcf matrix table"""
    info_ht = default_compute_info(mt, site_annotations=True, n_partitions=n_partitions)
    info_ht = info_ht.annotate(
        info=info_ht.info.annotate(DP=mt.rows()[info_ht.key].site_dp)
    )
    return info_ht


if __name__ == '__main__':
    main()  # pylint: disable=E1120
