# FFmpeg / x264 kaynakları

`scripts/build-ffmpeg.sh`, sürümü ve SHA-256 değeri sabitlenmiş özgün FFmpeg ve x264 kaynaklarını bu klasöre indirir. Kaynak arşivleri Git deposuna eklenmez; yayımlanan kurulum dosyasıyla aynı GitHub sürümündeki **Dikey-Studio-FFmpeg-Corresponding-Source.tar.gz** dosyasına dahil edilir.

Bu kaynak paketinde özgün tar arşivleri, lisanslar, derleme betiği, yapılandırma ve derleyici bilgileri birlikte bulunur. Video motorunun ağ desteği kapalıdır. FFmpeg dışında bağlanan tek medya kütüphanesi x264'tür. Standart Windows sistem kitaplıkları ve MinGW/GCC çalışma zamanı bildirimleri de korunur.

Sürümler ve doğrulama değerleri `scripts/build-ffmpeg.sh` ve `SHA256SUMS.txt` içindedir.
