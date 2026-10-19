# Docker 用法

镜像只含软件环境;FASTQ 与参考库(SILVA / 宿主基因组 / CheckM2 / KOfam,约 12 GB)通过挂载提供。

```bash
docker build -f docker/Dockerfile.pilot   -t metagsoil-pilot   .
docker build -f docker/Dockerfile.checkm2 -t metagsoil-checkm2 .

docker run --rm -it -v "$PWD":/work metagsoil-pilot \
  bash scripts/pilot/05a_maize_host_depletion.sh /work 24
```
