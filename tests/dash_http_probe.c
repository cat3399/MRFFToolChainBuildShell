/* Exercise the real libavformat API, including its terminal return value. */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "libavformat/avformat.h"
#include "libavutil/error.h"
#include "libavutil/time.h"

static int64_t deadline;

static int interrupted(void *opaque)
{
    (void)opaque;
    return deadline && av_gettime_relative() >= deadline;
}

int main(int argc, char **argv)
{
    AVFormatContext *ctx = avformat_alloc_context();
    AVPacket *pkt = av_packet_alloc();
    AVDictionary *opts = NULL;
    uint64_t hash = UINT64_C(14695981039346656037);
    int ret, packets = 0;

    if (argc < 3 || !ctx || !pkt)
        return 1;
    if (!strcmp(argv[1], "range")) {
        AVIOContext *pb = NULL;
        unsigned char buffer[128];
        int bytes = 0;
        av_dict_set(&opts, "reconnect", "1", 0);
        av_dict_set(&opts, "reconnect_delay_max", "0", 0);
        av_dict_set(&opts, "end_offset", "64", 0);
        ret = avio_open2(&pb, argv[2], AVIO_FLAG_READ, NULL, &opts);
        if (ret >= 0) {
            while ((ret = avio_read(pb, buffer, sizeof(buffer))) > 0)
                bytes += ret;
        }
        printf("bytes=%d eof=%d\n", bytes, ret == AVERROR_EOF);
        avio_closep(&pb);
        av_dict_free(&opts);
        av_packet_free(&pkt);
        avformat_free_context(ctx);
        return bytes == 64 && ret == AVERROR_EOF ? 0 : 2;
    }
    ctx->interrupt_callback.callback = interrupted;
    if (argc > 3)
        deadline = av_gettime_relative() + atoi(argv[3]) * INT64_C(1000);
    av_dict_set(&opts, "protocol_whitelist", "file,http,tcp,crypto,data", 0);
    av_dict_set(&opts, "reconnect", argv[2], 0);
    av_dict_set(&opts, "reconnect_max_retries", "2", 0);
    av_dict_set(&opts, "reconnect_delay_max", "0", 0);
    /* Exercise the existing IJK caller's timeout spelling. */
    av_dict_set(&opts, "timeout", "300000", 0);
    av_dict_set(&opts, "rw_timeout", "300000", 0);

    ret = avformat_open_input(&ctx, argv[1], NULL, &opts);
    av_dict_free(&opts);
    if (ret >= 0) {
        while ((ret = av_read_frame(ctx, pkt)) >= 0) {
            for (int i = 0; i < pkt->size; i++) {
                hash ^= pkt->data[i];
                hash *= UINT64_C(1099511628211);
            }
            packets++;
            av_packet_unref(pkt);
        }
    }
    printf("packets=%d hash=%016"PRIx64" ret=%d eof=%d exit=%d\n",
           packets, hash, ret, ret == AVERROR_EOF, ret == AVERROR_EXIT);
    av_packet_free(&pkt);
    avformat_close_input(&ctx);
    return ret == AVERROR_EOF ? 0 : 2;
}
