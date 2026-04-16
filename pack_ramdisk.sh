# 1. 进入 ramdisk 目录，打包为 cpio
cd out/ramdisk
find . | cpio -o -H newc > ../ramdisk_new.cpio
cd ..

# 2. gzip 压缩
gzip ramdisk_new.cpio
mv ramdisk_new.cpio.gz ramdisk_new.img

# 3. 验证新文件格式
file ramdisk_new.img
# 应该显示: ramdisk_new.img: gzip compressed data, original size modulo 2^32 XXXXXXX

rm -rf ramdisk.img
mv ramdisk_new.img ramdisk.img
