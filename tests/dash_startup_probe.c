/* Real libavformat startup/seek contract, with per-stream packet fingerprints. */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

#include "libavformat/avformat.h"
#include "libavutil/error.h"
#include "libavutil/mathematics.h"
#include "libavutil/opt.h"
#include "libavutil/time.h"

typedef struct StreamResult {
    uint64_t hash;
    int packets;
    int64_t first_pts;
    int64_t last_pts;
} StreamResult;

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
    StreamResult *results = NULL;
    int64_t started = av_gettime_relative();
    int64_t requested = argc > 2 ? strtoll(argv[2], NULL, 10) : 0;
    int64_t applied = 0;
    int ret, seek_ret = 0;

    if (argc < 2 || !ctx || !pkt)
        return 1;
    if (argc > 3 && atoi(argv[3]) > 0)
        deadline = started + atoi(argv[3]) * INT64_C(1000);
    ctx->interrupt_callback.callback = interrupted;
    av_dict_set(&opts, "protocol_whitelist", "file,http,tcp,crypto,data", 0);
    av_dict_set(&opts, "allowed_extensions", "ALL", 0);
    av_dict_set(&opts, "rw_timeout", "2500000", 0);
    av_dict_set(&opts, "cookies", "initial=1; path=/;\n", 0);
    if (requested > 0)
        av_dict_set_int(&opts, "initial_position", requested, 0);
    ret = avformat_open_input(&ctx, argv[1], NULL, &opts);
    av_dict_free(&opts);
    printf("open_ret=%d open_us=%"PRId64" exit=%d http404=%d\n",
           ret, av_gettime_relative() - started, ret == AVERROR_EXIT,
           ret == AVERROR_HTTP_NOT_FOUND);
    if (ret < 0)
        goto done;
    av_opt_get_int(ctx->priv_data, "initial_position_applied", 0, &applied);
    /* Match the player's contract: consumed != applied. */
    if (requested > 0 && !applied) {
        int64_t target = requested;
        if (ctx->start_time != AV_NOPTS_VALUE)
            target += ctx->start_time;
        seek_ret = avformat_seek_file(ctx, -1, INT64_MIN, target, INT64_MAX, 0);
    }
    printf("streams=%u applied=%"PRId64" seek_ret=%d\n",
           ctx->nb_streams, applied, seek_ret);
    results = calloc(ctx->nb_streams, sizeof(*results));
    if (!results) {
        ret = AVERROR(ENOMEM);
        goto done;
    }
    for (unsigned i = 0; i < ctx->nb_streams; i++) {
        results[i].hash = UINT64_C(14695981039346656037);
        results[i].first_pts = AV_NOPTS_VALUE;
        results[i].last_pts = AV_NOPTS_VALUE;
    }
    while ((ret = av_read_frame(ctx, pkt)) >= 0) {
        StreamResult *result = &results[pkt->stream_index];
        if (!result->packets)
            result->first_pts = pkt->pts;
        for (int i = 0; i < pkt->size; i++) {
            result->hash ^= pkt->data[i];
            result->hash *= UINT64_C(1099511628211);
        }
        result->packets++;
        result->last_pts = pkt->pts;
        printf("packet_stream=%d hash=%016"PRIx64"\n", pkt->stream_index,
               result->hash);
        av_packet_unref(pkt);
    }
    for (unsigned i = 0; i < ctx->nb_streams; i++) {
        printf("stream=%u type=%s packets=%d hash=%016"PRIx64
               " first_pts_us=%"PRId64" last_pts_us=%"PRId64"\n",
               i, av_get_media_type_string(ctx->streams[i]->codecpar->codec_type),
               results[i].packets, results[i].hash,
               results[i].first_pts == AV_NOPTS_VALUE ? AV_NOPTS_VALUE :
               av_rescale_q(results[i].first_pts, ctx->streams[i]->time_base,
                            AV_TIME_BASE_Q),
               results[i].last_pts == AV_NOPTS_VALUE ? AV_NOPTS_VALUE :
               av_rescale_q(results[i].last_pts, ctx->streams[i]->time_base,
                            AV_TIME_BASE_Q));
    }
done:
    printf("ret=%d eof=%d\n", ret, ret == AVERROR_EOF);
    free(results);
    av_packet_free(&pkt);
    avformat_close_input(&ctx);
    return ret == AVERROR_EOF && seek_ret >= 0 ? 0 : 2;
}
