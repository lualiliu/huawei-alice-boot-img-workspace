cd out
# 1. 复制一份（保留原始文件）
cp ramdisk.img ramdisk.img.backup

# 2. 重命名并解压 gzip
mv ramdisk.img ramdisk.img.gz
gunzip ramdisk.img.gz
# 解压后得到 ramdisk.img 文件（现在是 cpio 归档，不再是 gzip）

# 3. 创建目录并解包 cpio
mkdir ramdisk
cd ramdisk
cpio -i -F ../ramdisk.img
cd ..
