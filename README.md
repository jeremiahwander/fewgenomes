# Fewgenomes

Preparing a test dataset for continuous evaluation of single-sample and joint variant calling analysis.


## Installation

Install the environment with conda:

```bash
conda env create -n fewgenomes -f environment.yml
```


## Sample selection

As a baseline, we picked 1 trio from the 1000genomes project (NA19238, NA19239, NA19240) of the YRI ancestry, as well NA12878 of CEU ancestry as it's a genome with a validated truth set.

One top of that, we randomly selected samples from different families and ancestries from the 1000genomes project, as long as there is data available at the Google public genomics bucket: (`gs://genomics-public-data/ftp-trace.ncbi.nih.gov/1000genomes/ftp/phase3/data/`). 

A [toy dataset](datasets/toy/samples.ped) of 6 samples ended up containing exomes for individuals from 4 families of 3 ancestries, with 50% females and 50% males. To generate it:

```bash
snakemake -s prep_warp_inputs.smk -j1 -p --config n=6 input_type=exome_bam dataset_name=toy
```

A larger [50-sample dataset](datasets/50genomes/samples.ped) ended up containing genomes from 48 families of 18 ancestries with a roughly equal male/female distribution. To generate it:

```bash
snakemake -s prep_warp_inputs.smk -j1 -p --config n=50 input_type=wgs_bam dataset_name=50genomes
```

These scripts run the workflow [prep_warp_inputs.smk](prep_warp_inputs.smk), which:
1. pulls the 1000genomes project metadata from [the 1000genomes FTP](ftp://ftp.1000genomes.ebi.ac.uk/vol1/ftp/technical/),
2. overlaps it with the data available at `gs://genomics-public-data/ftp-trace.ncbi.nih.gov/1000genomes/ftp/phase3/data/` according to the requested `input_type` (options: `wgs_fastq`, `wgs_bam`, `wgs_bam_highcov`, `exome_bam`),
3. selects a subset of the requested number of samples,
4. generates input JSON files for the germline single-sample variant calling 
   [WDL workflows](https://github.com/populationgenomics/warp/blob/start_from_mapped_bam/pipelines/broad/dna_seq/germline/single_sample/), 
   which are based and built on top of 
   [Broad WARP workflows](https://github.com/broadinstitute/warp/),
5. generates an input JSON for the 
   [WGSMultipleSamplesFromBam](https://github.com/populationgenomics/warp/pull/3) 
   workflow, that runs single-sample workflows in parallel,
6. generates a PED file for the subset.

The WDL inputs are written into `datasets/<dataset_name>/<input_type>/`, and 
can be used along with Cromwell configs, to execute a pipeline on Google 
Cloud to generate GVCFs.

```bash
conda install cromwell==55
git clone https://github.com/populationgenomics/warp
git clone https://github.com/populationgenomics/cromwell-configs
# edit templates in `cromwell-configs` to replace <project> and <bucket>, and save as `cromwell.conf` and `options.json`

# To run a single-sample workflow:
SAMPLE=NA19238
cromwell -Dconfig.file=cromwell-configs/cromwell.conf run \
    warp/pipelines/broad/dna_seq/germline/single_sample/wgs/WGSFromBam.wdl \
    --inputs datasets/50genomes/wgs_bam/${SAMPLE}-warp.json \
    --options cromwell-configs/options.json
    
# To run the multi-sample workflow:
cromwell -Dconfig.file=cromwell-configs/cromwell.conf run \
    warp/pipelines/broad/dna_seq/germline/single_sample/wgs/WGSMultipleSamplesFromBam.wdl \
    --inputs datasets/50genomes/50genomes-warp-wgs_bam.json \
    --options cromwell-configs/options.json
```

## GVCF input

You can also generate the input from publicly available 1000genomes GVCFs with `input_type=gvcf`:

```bash
snakemake -s prep_warp_inputs.smk -j1 -p --config n=50 input_type=gvcf dataset_name=50genomes-gvcf copy_localy='gs://cpg-fewgenomes-temporary'
```

The `copy_locally` flag makes the workflow transfer the GVCFs to the target bucket.

The following WDL workflow prepares the GVCFs for Hail:

```bash
cromwell -Dconfig.file=cromwell-configs/cromwell.conf run \
  wdl/prepare-gvcfs.wdl \
  --inputs datasets/50genomes-gvcf/50genomes-gvcf-gvcf-test.json \
  --options cromwell-configs/options.json
```

It runs ReblockGVCF to add some INFO annotations, and removes variants in non-standard reference contigs.


## Prepare inputs for the GVCF combiner

After running Cromwell, you can use the following script to generate inputs for the [`combine_gvcfs.py` script](https://github.com/populationgenomics/joint-calling-workflow). Example of usage:

```bash
python prep_inputs_for_combiner.py \
   --dataset 50genomes-gvcf \
   --split-rounds \
   --randomise-pop-labels \
   --move-locally \
   --warp-executions-bucket gs://cpg-fewgenomes-temporary/cromwell/outputs/
```

It will write sample maps csv files to `datasets/50genomes/sample-maps`:

```text
$ cat datasets/50genomes-gvcf/sample-maps
50genomes-gvcf-all.csv  50genomes-gvcf-round1.csv  50genomes-gvcf-round2.csv
```

Full list of options:

```text
  --dataset TEXT                 Dataset name, e.g. "fewgenomes". Assumes that
                                 `{datasets_dir}/{datasets_name}/samples.ped`
                                 exists.  [required]

  --warp-executions-bucket TEXT  Bucket with WARP workflow outputs
  --datasets-dir TEXT            Output folder. Default is "datasets/"
  --work-dir TEXT                Directory to store temporary files
  --split-rounds                 Break samples into 2 groups to produce tests
                                 for the gVCF combiner

  --randomise-pop-labels         Remove population labels for 1/3 of the
                                 samples to test sample-qc ancestry detection

  --move-locally                 Move GVCFs and picard files to the gs://cpg-
                                 fewgenomes-upload bucket
```

## gnomAD Matrix Table subset

Script `hail_subset_gnomad.py` subsets the gnomAD matrix table (`gs://gcp-public-data--gnomad/release/3.1/mt/genomes/gnomad.genomes.v3.1.hgdp_1kg_subset_dense.mt/`) to the samples in the test dataset. To run it, put the PED file generated by the Snakemake workflow above on a Google Storage bucket, and submit the script to a Hail Dataproc cluster, pointing it to the PED file as follows:

```bash
# Upload the PED file
gsutil cp datasets/toy/samples.ped gs://playground-us-central1/fewgenomes/datasets/toy/samples.ped

# Create the Dataproc cluster
hailctl dataproc start fewgenomes --region us-central1 --zone us-central1-a --max-age 12h

# Run the script with the PED file as a parameter
hailctl dataproc submit fewgenomes --region us-central1 --zone us-central1-a hail_subset_gnomad.py gs://playground-us-central1/fewgenomes/datasets/toy/samples.ped

# Stop the cluster
hailctl dataproc stop fewgenomes --region us-central1
```

The result will be written into the same base location as the PED file, i.e. for the example above you will be able to find it as `gs://playground-us-central1/fewgenomes/datasets/toy/gnomad.subset.mt`
