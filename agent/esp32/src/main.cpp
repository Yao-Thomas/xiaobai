#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <driver/i2s.h>
#include <mbedtls/base64.h>

#define WIFI_SSID        "001"
#define WIFI_PASSWORD    "yaoenqi127"
#define BAIDU_API_KEY    "YOUR_BAIDU_API_KEY_HERE"
#define BAIDU_SECRET_KEY "nO6hChLTHI7Kor7hxFphZ0AJZC7dT76b"
#define DEEPSEEK_KEY "YOUR_DEEPSEEK_API_KEY_HERE"

#define I2S_WS  15
#define I2S_SCK 16
#define I2S_SD  17


// ===== 喇叭引脚 =====
#define SPK_BCLK  5
#define SPK_LRC   4
#define SPK_DOUT  6


#define SAMPLE_RATE    16000
#define RECORD_SECONDS 3
#define SAMPLE_BYTES   (SAMPLE_RATE * RECORD_SECONDS * 2)

int16_t* audio_buf    = nullptr;
char*    b64_buf      = nullptr;
size_t   b64_len      = 0;
String   access_token = "";


#define BOOT_BTN 0

bool          last_btn    = HIGH;
unsigned long last_btn_ms = 0;


// ===== 喇叭初始化 =====
void i2s_speaker_init() {
    i2s_config_t spk_cfg = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = 16000,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 512,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0
    };
    i2s_pin_config_t spk_pins = {
        .bck_io_num   = SPK_BCLK,
        .ws_io_num    = SPK_LRC,
        .data_out_num = SPK_DOUT,
        .data_in_num  = I2S_PIN_NO_CHANGE
    };
    i2s_driver_install(I2S_NUM_1, &spk_cfg, 0, NULL);
    i2s_set_pin(I2S_NUM_1, &spk_pins);
    Serial.println("[SPK] 喇叭初始化OK");
}

// ===== 播放提示音 =====
void play_beep(int freq, int duration_ms) {
    int sample_rate = 16000;
    int samples = sample_rate * duration_ms / 1000;
    int16_t* buf = (int16_t*)ps_malloc(samples * 2);
    if(!buf) return;
    for(int i = 0; i < samples; i++)
        buf[i] = (int16_t)(6000 * sin(2.0 * M_PI * freq * i / sample_rate));
    size_t bytes_written;
    i2s_write(I2S_NUM_1, buf, samples * 2, &bytes_written, portMAX_DELAY);
    free(buf);
}

// ===== 播报导航提示音 =====
// 不同方向播不同节奏的提示音
void play_direction_beep(uint8_t direction) {
    switch(direction) {
        case 0: // 直行：一声长音
            play_beep(1000, 600);
            break;
        case 2: // 右转：两声短音
            play_beep(1200, 200); delay(100);
            play_beep(1200, 200);
            break;
        case 6: // 左转：两声低音
            play_beep(800, 200); delay(100);
            play_beep(800, 200);
            break;
        case 4: // 掉头：三声音
            play_beep(600, 200); delay(100);
            play_beep(600, 200); delay(100);
            play_beep(600, 200);
            break;
        default: // 其他方向：一声短音
            play_beep(1000, 300);
            break;
    }
}

// ===== 百度TTS语音合成 =====
void baidu_tts(String text) {
    if(access_token.length() == 0) {
        Serial.println("[TTS] 无token");
        play_beep(800, 300);
        return;
    }
    
    Serial.println("[TTS] 合成: " + text);
    
    // 构造TTS请求URL
    // URL编码中文
String encoded = "";
for(int i = 0; i < (int)text.length(); i++) {
    unsigned char c = (unsigned char)text[i];
    if((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || 
       (c >= '0' && c <= '9') || c=='-' || c=='_' || c=='.' || c=='~') {
        encoded += (char)c;
    } else {
        char buf[4];
        sprintf(buf, "%%%02X", c);
        encoded += buf;
    }
}

    String url = "http://tsn.baidu.com/text2audio"
                "?tex=" + encoded +
                 "&tok=" + access_token +
                 "&cuid=esp32s3" +
                 "&ctp=1" +
                 "&lan=zh" +
                 "&spd=5" +   // 语速5（1-15）
                 "&pit=5" +   // 音调5（1-15）
                 "&vol=10" +  // 音量10（1-15）
                 "&per=0" +   // 发音人0=女声
                 "&aue=6";    // 返回PCM格式（16bit/16kHz）
    
    HTTPClient http;
    http.begin(url);
    http.setTimeout(15000);
    int code = http.GET();
    Serial.printf("[TTS] HTTP=%d\n", code);
    
    if(code != 200) {
        Serial.println("[TTS] 失败: " + http.getString().substring(0, 100));
        http.end();
        play_beep(600, 300);
        return;
    }
    
    // 流式读取PCM数据直接播放
    WiFiClient* stream = http.getStreamPtr();
    uint8_t pcm_buf[1024];
    size_t bytes_written;
    int total = 0;
    
    while(http.connected() || stream->available()) {
        int avail = stream->available();
        if(avail > 0) {
            int to_read = min(avail, (int)sizeof(pcm_buf));
            int read = stream->readBytes(pcm_buf, to_read);
            i2s_write(I2S_NUM_1, pcm_buf, read, &bytes_written, portMAX_DELAY);
            total += read;
        }
        delay(1);
    }
    http.end();
    Serial.printf("[TTS] 播放完成 %d bytes\n", total);
}







// ===== DeepSeek理解意图 =====
String deepseek_understand(String user_text) {
    Serial.println("[DS] 发送: " + user_text);

   String sys = "你是一个智能导航眼镜的AI助手，由DeepSeek驱动，能力全面。"
    "你可以回答任何问题，包括知识问答、计算、写作、分析等。"
    "同时你也支持导航功能。"
    "已知导航坐标：操场(24.5613,118.5856)，图书馆(24.5620,118.5840)，食堂(24.5615,118.5830)，宿舍(24.5618,118.5825)。"
    "当前位置在宿舍，如果用户没说出发地，默认是宿舍。"
    "如果用户明确说从固定位置/宿舍/当前宿舍出发，destination前加FIXED前缀，格式："
"{\\\"type\\\":\\\"navigate\\\",\\\"fixed\\\":true,\\\"destination\\\":\\\"地点\\\",\\\"lat\\\":纬度,\\\"lon\\\":经度,\\\"reply\\\":\\\"回复\\\"}"
    "根据用户输入判断意图，返回JSON格式："
    "导航请求返回：{\\\"type\\\":\\\"navigate\\\",\\\"destination\\\":\\\"地点\\\",\\\"lat\\\":纬度,\\\"lon\\\":经度,\\\"reply\\\":\\\"回复\\\"}"
    "其他所有请求返回：{\\\"type\\\":\\\"chat\\\",\\\"reply\\\":\\\"你的完整回答\\\"}"
    "只返回JSON，不要其他内容。";

    String body = "{\"model\":\"deepseek-chat\",\"messages\":["
                  "{\"role\":\"system\",\"content\":\"" + sys + "\"},"
                  "{\"role\":\"user\",\"content\":\"" + user_text + "\"}"
                  "],\"max_tokens\":200,\"temperature\":0.1}";

    HTTPClient http;
    http.begin("https://api.deepseek.com/chat/completions");
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", "Bearer " + String(DEEPSEEK_KEY));
    http.setTimeout(20000);
    int code = http.POST(body);
    Serial.printf("[DS] HTTP=%d\n", code);
    if(code != 200) {
        Serial.println("[DS] 错误: " + http.getString().substring(0, 100));
        http.end();
        return "";
    }


    
    // 分批读取，边读边拼接关键内容
String resp = "";
WiFiClient* stream = http.getStreamPtr();
uint8_t buf[256];
bool found_content = false;

while(http.connected() || stream->available()) {
    int avail = stream->available();
    if(avail > 0) {
        int to_read = min(avail, (int)sizeof(buf) - 1);
        int read = stream->readBytes(buf, to_read);
        buf[read] = 0;
        resp += (char*)buf;

        // 找到content字段开始后，只保留后面2000字节
        // 避免resp无限增长
        if(resp.length() > 3000) {
            // 找到content起点就截断前面的HTTP头
            int cut = resp.indexOf("\"content\":\"");
            if(cut > 0) {
                resp = resp.substring(cut);
            } else {
                // 还没找到content，丢掉前面的
                resp = resp.substring(resp.length() - 500);
            }
        }

        // 找到closing_reason说明内容完整了
        if(resp.indexOf("finish_reason") >= 0) break;
    }
    delay(1);
}
http.end();
Serial.println("[DS] 读取完成，长度: " + String(resp.length()));




    // 提取content（处理转义和换行）
    int idx = resp.indexOf("\"content\":\"");
    if(idx < 0) {
        // 有些情况content不带引号转义，尝试另一种格式
        Serial.println("[DS] 原始返回: " + resp.substring(0, 300));
        return "";
    }
    idx += 11;
    String content = "";
    bool esc = false;
    for(int i = idx; i < (int)resp.length() && i < idx+2000; i++) {
        char c = resp[i];
        if(esc) {
            if(c == 'n') content += ' ';      // 换行转空格
            else if(c == 't') content += ' '; // tab转空格
            else if(c == '"') content += '"';
            else if(c == '\\') content += '\\';
            else if(c == 'u') {               // unicode转义跳过
                i += 4;
            }
            esc = false;
        } else if(c == '\\') esc = true;
        else if(c == '"') break;
        else content += c;
    }
    Serial.println("[DS] 内容: " + content);
    return content;
}

// ===== 解析DeepSeek结果 =====
void process_result(String j) {
    int t = j.indexOf("\"type\":\"");
    if(t < 0) { Serial.println("[DS] 解析失败"); return; }
    t += 8;
    String type = j.substring(t, j.indexOf("\"", t));

    int r = j.indexOf("\"reply\":\"");
    String reply = "";
    if(r >= 0) { r += 9; reply = j.substring(r, j.indexOf("\"", r)); }

    if(type == "navigate") {
        int d = j.indexOf("\"destination\":\"");
        String dest = "";
        if(d >= 0) { d += 15; dest = j.substring(d, j.indexOf("\"", d)); }
        int la = j.indexOf("\"lat\":");
        int lo = j.indexOf("\"lon\":");
        float lat = 0, lon = 0;
        if(la >= 0) lat = j.substring(la+6, j.indexOf(",", la+6)).toFloat();
        if(lo >= 0) lon = j.substring(lo+6, j.indexOf("}", lo+6)).toFloat();
        Serial.println("==================");
        Serial.println("导航至: " + dest);
        Serial.printf("坐标: %.4f, %.4f\n", lat, lon);
        Serial.println("语音: " + reply);
        Serial.println("==================");
        // 发送导航坐标给STM32N647
    // 判断是否用固定坐标
    bool is_fixed = (j.indexOf("\"fixed\":true") >= 0);
    char stm32_msg[64];
    if(is_fixed)
        snprintf(stm32_msg, sizeof(stm32_msg), "FIXED:%.4f,%.4f\r\n", lat, lon);
    else
        snprintf(stm32_msg, sizeof(stm32_msg), "DEST:%.4f,%.4f\r\n", lat, lon);
    Serial1.print(stm32_msg);
    Serial.println("[STM32] 已发送: " + String(stm32_msg));
    // 语音播报导航回复
    baidu_tts(reply);
    } else {
        Serial.println("==================");
        Serial.println("回复: " + reply);
        Serial.println("==================");
        // 收到回复提示音
        baidu_tts(reply);
    }
}


void setup() {
    pinMode(BOOT_BTN, INPUT_PULLUP);
    Serial.begin(115200);
    uint32_t t = millis();
    while(!Serial && millis()-t < 10000);

    Serial.println("=== ESP32-S3 语音识别 ===");

    // WiFi连接（你的可用版本不动）
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[WiFi] 连接中");
    int cnt = 0;
    while(WiFi.status() != WL_CONNECTED && cnt < 40) {
        delay(500); Serial.print("."); cnt++;
    }
    if(WiFi.status() == WL_CONNECTED) {
        Serial.println("\n[WiFi] OK: " + WiFi.localIP().toString());
    } else {
        Serial.println("\n[WiFi] 失败!"); return;
    }

    // 分配PSRAM
    audio_buf = (int16_t*)ps_malloc(SAMPLE_BYTES);
    b64_buf   = (char*)ps_malloc(SAMPLE_BYTES * 2);
    if(!audio_buf || !b64_buf) {
        Serial.println("[ERR] PSRAM失败!"); return;
    }
    Serial.println("[MEM] PSRAM OK");

    // I2S初始化
    i2s_config_t cfg = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 512,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0
    };
    i2s_pin_config_t pins = {
        .bck_io_num   = I2S_SCK,
        .ws_io_num    = I2S_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num  = I2S_SD
    };
    i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
    i2s_set_pin(I2S_NUM_0, &pins);
    Serial.println("[I2S] OK");




    // 初始化喇叭
    i2s_speaker_init();
    // 开机提示音
    play_beep(1000, 200); delay(100);
    play_beep(1500, 200);




    // 初始化Serial1发给STM32N647
    Serial1.begin(115200, SERIAL_8N1, 44, 43);
    Serial.println("[UART] STM32串口OK");


    
    // 获取百度token
    Serial.println("[TOKEN] 获取中...");
    HTTPClient http;
    String url = "https://aip.baidubce.com/oauth/2.0/token"
                 "?grant_type=client_credentials&client_id=" +
                 String(BAIDU_API_KEY) +
                 "&client_secret=" + String(BAIDU_SECRET_KEY);
    http.begin(url);
    int code = http.GET();
    if(code == 200) {
        String resp = http.getString();
        int idx = resp.indexOf("\"access_token\":\"");
        if(idx >= 0) {
            idx += 16;
            access_token = resp.substring(idx, resp.indexOf("\"", idx));
            Serial.println("[TOKEN] OK: " + access_token.substring(0,20) + "...");
        }
    } else {
        Serial.println("[TOKEN] 失败 HTTP=" + String(code));
    }
    http.end();

    Serial.println("\n就绪! 发任意字符开始录音...");
}

void loop() {
    bool trigger = false;

    // 串口触发放最前，保证任何情况下都能响应
    if(Serial.available()) {
        while(Serial.available()) Serial.read();
        trigger = true;
    }

    // 按钮边沿检测（非阻塞，不会卡死）
    bool now = digitalRead(BOOT_BTN);
    if(last_btn == HIGH && now == LOW && millis() - last_btn_ms > 200) {
        trigger = true;
        last_btn_ms = millis();
    }
    last_btn = now;

    if(!trigger) { delay(20); return; }

    play_beep(1500, 120);   // "叮"表示开始录音

    
    // 录音
   Serial.println("\n[REC] 录音3秒，请说话...");
int32_t tmp[512];
size_t  bytes_read;
int     total = 0, max_s = SAMPLE_RATE * RECORD_SECONDS;
while(total < max_s) {
    i2s_read(I2S_NUM_0, tmp, sizeof(tmp), &bytes_read, portMAX_DELAY);
    int got = bytes_read / 4;
    for(int i = 0; i < got && total < max_s; i++) {
        int32_t sample = tmp[i] >> 8;
        sample = sample * 4;
        if(sample > 32767)  sample = 32767;
        if(sample < -32768) sample = -32768;
        audio_buf[total++] = (int16_t)sample;
    }
}
Serial.println("[REC] 完成");

    // Base64编码
    size_t needed = ((SAMPLE_BYTES + 2) / 3) * 4 + 4;
    mbedtls_base64_encode(
        (unsigned char*)b64_buf, needed, &b64_len,
        (const unsigned char*)audio_buf, SAMPLE_BYTES);
    b64_buf[b64_len] = 0;
    Serial.printf("[B64] %d bytes\n", (int)b64_len);

    // 发送识别
    Serial.println("[ASR] 发送中...");
    String body = "{\"format\":\"pcm\",\"rate\":16000,\"channel\":1,"
                  "\"cuid\":\"esp32s3\",\"token\":\"" + access_token + "\","
                  "\"len\":" + String(SAMPLE_BYTES) + ",\"speech\":\"" +
                  String(b64_buf) + "\"}";
    HTTPClient http2;
    http2.begin("https://vop.baidu.com/server_api");
    http2.addHeader("Content-Type", "application/json");
    http2.setTimeout(15000);
    int code2 = http2.POST(body);
    String result = "HTTP_ERR_" + String(code2);
    if(code2 == 200) {
        String resp = http2.getString();
        Serial.println("[ASR] 返回: " + resp.substring(0, 100));
        int idx = resp.indexOf("\"result\":[\"");
        if(idx >= 0) {
            idx += 11;
            result = resp.substring(idx, resp.indexOf("\"", idx));
        } else {
            result = "NO_RESULT";
        }
    }
    http2.end();

   Serial.println("识别结果: " + result);

    // 把识别结果交给DeepSeek理解
    if(result.length() > 0 && result != "NO_RESULT" && result.indexOf("HTTP_ERR") < 0) {
        String ds = deepseek_understand(result);
        if(ds.length() > 0) {
            process_result(ds);
        } else {
            Serial.println("[DS] 无返回");
        }
    }

    Serial.println("\n再发字符继续...");
}