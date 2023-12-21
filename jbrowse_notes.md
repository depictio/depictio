docker exec -it e8c7db65171d21fdbcf68cae31fcc4684b9555731da15986e0295bcf97220cf4 jbrowse add-assembly /mnt/chr17.fa.gz --load copy

docker exec -it c53f197b071b06b1625c8c612afa97a6ac0cd81619eaf9cbaabf5fb7bd0115ed jbrowse add-track /Users/tweber/Gits/ashleys_qc_dash/assets/Counts_BW/BM510x04_PE20304-C.bigWig --load symlink --subDir TEST_BM510

docker exec -it c53f197b071b06b1625c8c612afa97a6ac0cd81619eaf9cbaabf5fb7bd0115ed jbrowse add-track http://127.0.0.
1:9000/depictio-bucket/BM510x04_PE20301.sort.mdup.bam


# Notes

* Custom JSON tracks for BigWig and BED functional (see /Users/tweber/Gits/jbrowse2_config/jbrowse2/BM510x04_PE20301.json and /Users/tweber/Gits/jbrowse2_config/jbrowse2/BM510x04_PE20301-SV.json)
* Reading from HTTP through S3 functional
* Implementation of the interface to select & choose
  * Provide a way to push JSON through jbrowse CLI with docker?
  * Everything handled by depictio: interface is YAML
* Data organisation model to choose:
  * Push everything to a S3 handled by the instance
  * Handle remote data / local storage (potentially corrupted data / removed / moved ...)
  * Push to S3 except if present in LabID
* How to accurately organise data:
  * Sessions
  * Categories
  * Subfolders ...
* How to provide interactivity through depictio interactive components: modify config.json directly?   
