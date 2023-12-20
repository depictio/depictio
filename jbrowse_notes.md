docker exec -it e8c7db65171d21fdbcf68cae31fcc4684b9555731da15986e0295bcf97220cf4 jbrowse add-assembly /mnt/chr17.fa.gz --load copy

docker exec -it c53f197b071b06b1625c8c612afa97a6ac0cd81619eaf9cbaabf5fb7bd0115ed jbrowse add-track /Users/tweber/Gits/ashleys_qc_dash/assets/Counts_BW/BM510x04_PE20304-C.bigWig --load symlink --subDir TEST_BM510

docker exec -it c53f197b071b06b1625c8c612afa97a6ac0cd81619eaf9cbaabf5fb7bd0115ed jbrowse add-track http://127.0.0.
1:9000/depictio-bucket/BM510x04_PE20301.sort.mdup.bam