#!/bin/bash
# =============================================================================
#  Prime Stage - OBS 直式設定 (macOS)  對應 Windows setup.ps1 v8
#  用法: ./setup_mac.sh "串流金鑰"   (金鑰留空=跳 GUI 輸入框)
# =============================================================================
set -uo pipefail

KEY="${1:-}"
SERVER="${PRIMESTAGE_SERVER:-rtmps://af36b0817398.global-contribute.live-video.net:443/app/}"
PROFILE="Prime Stage 直式"
BASEW=720; BASEH=1280; FPS=30; VBITRATE=2500; ABITRATE=160
# Apple VT 硬體編碼器 id(需在 Mac 實測;不行改 obs_x264)
ENCODER_ID="${PRIMESTAGE_ENCODER:-com.apple.videotoolbox.videoencoder.ave.avc}"

OBS_ROOT="$HOME/Library/Application Support/obs-studio"
PS_DIR="$HOME/Library/Application Support/PrimeStage"
PROF_DIR="$OBS_ROOT/basic/profiles/$PROFILE"
SCENES_DIR="$OBS_ROOT/basic/scenes"
mkdir -p "$PROF_DIR" "$SCENES_DIR" "$PS_DIR"

# 升級刷新保留舊金鑰:先讀 service.json 現有金鑰
OLD_KEY=""
if [ -f "$PROF_DIR/service.json" ]; then
  OLD_KEY=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['settings'].get('key',''))" "$PROF_DIR/service.json" 2>/dev/null || echo "")
fi
if [ -z "$KEY" ] && [ -n "$OLD_KEY" ]; then KEY="$OLD_KEY"; fi   # 已有金鑰(升級)→沿用,不重問
if [ -z "$KEY" ] && [ "${NOPROMPT:-}" != "1" ]; then
  KEY=$(osascript -e 'text returned of (display dialog "請貼上你的「串流金鑰」\n(直播主後台 → 設定 → OBS平台金鑰 → 複製)\n只會存在你這台電腦。" default answer "" with title "Prime Stage 設定")' 2>/dev/null || echo "")
fi
KEY="$(echo -n "$KEY" | tr -d '[:space:]')"
[ -z "$KEY" ] && KEY="$OLD_KEY"   # 取消也不清掉舊金鑰

# ---- profile ----
cat > "$PROF_DIR/basic.ini" <<EOF
[General]
Name=$PROFILE

[Output]
Mode=Advanced
Reconnect=true
RetryDelay=2
MaxRetries=25

[Stream1]
IgnoreRecommended=true
EnableMultitrackVideo=false

[AdvOut]
ApplyServiceSettings=false
TrackIndex=1
Encoder=$ENCODER_ID
AudioEncoder=ffmpeg_aac
RecEncoder=none
Track1Bitrate=$ABITRATE

[Video]
BaseCX=$BASEW
BaseCY=$BASEH
OutputCX=$BASEW
OutputCY=$BASEH
FPSType=0
FPSCommon=$FPS
ScaleType=bicubic
ColorFormat=NV12
ColorSpace=709
ColorRange=Partial

[Audio]
SampleRate=48000
ChannelSetup=Stereo
EOF

cat > "$PROF_DIR/streamEncoder.json" <<EOF
{ "bitrate": $VBITRATE, "rate_control": "CBR", "keyint_sec": 2, "profile": "baseline", "bframes": false }
EOF

cat > "$PROF_DIR/service.json" <<EOF
{ "type": "rtmp_custom", "settings": { "server": "$SERVER", "key": "$KEY", "use_auth": false, "bwtest": false } }
EOF

# ---- 場景(攝影機=引擎輸出的 OBS Virtual Camera;mac 用 av_capture,以名稱指定需實測) ----
cat > "$SCENES_DIR/$PROFILE.json" <<EOF
{
  "name": "$PROFILE",
  "AuxAudioDevice1": {
    "prev_ver": 536936450, "name": "麥克風", "uuid": "a1b2c3d4-0004-4000-8000-primestagem01",
    "id": "coreaudio_input_capture", "versioned_id": "coreaudio_input_capture",
    "settings": { "device_id": "default" },
    "mixers": 255, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5, "enabled": true, "muted": false,
    "push-to-mute": false, "push-to-mute-delay": 0, "push-to-talk": false, "push-to-talk-delay": 0,
    "hotkeys": {}, "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0, "private_settings": {}
  },
  "sources": [
    {
      "prev_ver": 536936450, "name": "攝影機", "uuid": "a1b2c3d4-0001-4000-8000-primestagec01",
      "id": "av_capture_input", "versioned_id": "av_capture_input",
      "settings": { "device_name": "OBS Virtual Camera" },
      "mixers": 255, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5, "enabled": true, "muted": false,
      "push-to-mute": false, "push-to-mute-delay": 0, "push-to-talk": false, "push-to-talk-delay": 0,
      "hotkeys": {}, "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0, "private_settings": {}
    },
    {
      "prev_ver": 536936450, "name": "場景", "uuid": "a1b2c3d4-0002-4000-8000-primestages01",
      "id": "scene", "versioned_id": "scene",
      "settings": { "id_counter": 1, "custom_size": false, "items": [
        { "name": "攝影機", "source_uuid": "a1b2c3d4-0001-4000-8000-primestagec01",
          "visible": true, "locked": false, "rot": 0.0,
          "scale_ref": { "x": $BASEW.0, "y": $BASEH.0 },
          "align": 5, "bounds_type": 3, "bounds_align": 0, "bounds_crop": false,
          "crop_left": 0, "crop_top": 0, "crop_right": 0, "crop_bottom": 0,
          "id": 1, "group_item_backup": false,
          "pos": { "x": 0.0, "y": 0.0 }, "scale": { "x": 1.0, "y": 1.0 },
          "bounds": { "x": $BASEW.0, "y": $BASEH.0 },
          "scale_filter": "disable", "blend_method": "default", "blend_type": "normal",
          "show_transition": { "duration": 300 }, "hide_transition": { "duration": 300 },
          "private_settings": {} } ] },
      "mixers": 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5, "enabled": true, "muted": false,
      "push-to-mute": false, "push-to-mute-delay": 0, "push-to-talk": false, "push-to-talk-delay": 0,
      "hotkeys": {}, "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0,
      "canvas_uuid": "6c69626f-6273-4c00-9d88-c5136d61696e", "private_settings": {}
    }
  ],
  "groups": [], "scene_order": [ { "name": "場景" } ],
  "current_scene": "場景", "current_program_scene": "場景", "canvases": [],
  "current_transition": "淡入淡出", "transition_duration": 300, "transitions": [],
  "saved_projectors": [], "preview_locked": false, "scaling_enabled": false,
  "virtual-camera": { "type2": 3 }, "modules": {},
  "resolution": { "x": $BASEW, "y": $BASEH }, "version": 2
}
EOF

# ---- user.ini / global.ini:一律寫(不存在就建,含 FirstRun 壓精靈+關自動更新) ----
write_basic() {
  local ini="$1"
  local block="[Basic]
Profile=$PROFILE
ProfileDir=$PROFILE
SceneCollection=$PROFILE
SceneCollectionFile=$PROFILE"
  if [ -f "$ini" ]; then
    cp "$ini" "$ini.primestage.bak" 2>/dev/null || true
    if grep -q '^\[Basic\]' "$ini"; then
      awk -v repl="$block" '/^\[Basic\]/{print repl; skip=1; next} skip==1 && /^\[/{skip=0} skip==1{next} {print}' \
        "$ini" > "$ini.tmp" && mv "$ini.tmp" "$ini"
    else
      printf '\n%s\n' "$block" >> "$ini"
    fi
  else
    printf '[General]\nFirstRun=true\nEnableAutoUpdates=false\n\n%s\n' "$block" > "$ini"
  fi
  # 確保關閉自動更新提示
  if grep -q 'EnableAutoUpdates=' "$ini"; then
    sed -i '' 's/EnableAutoUpdates=.*/EnableAutoUpdates=false/' "$ini" 2>/dev/null || true
  fi
}
write_basic "$OBS_ROOT/user.ini"
write_basic "$OBS_ROOT/global.ini"

# ---- OBS WebSocket(隨機密碼;引擎「開始直播」鈕遙控用) ----
WS_JSON="$PS_DIR/obsws.json"
if [ -f "$WS_JSON" ]; then
  WSPWD=$(python3 -c "import json;print(json.load(open('$WS_JSON'))['password'])" 2>/dev/null || uuidgen | tr -d '-')
else
  WSPWD=$(uuidgen | tr -d '-')
fi
mkdir -p "$OBS_ROOT/plugin_config/obs-websocket"
printf '{"alerts_enabled":false,"auth_required":true,"first_load":false,"server_enabled":true,"server_password":"%s","server_port":4455}' "$WSPWD" \
  > "$OBS_ROOT/plugin_config/obs-websocket/config.json"
printf '{"port":4455,"password":"%s"}' "$WSPWD" > "$WS_JSON"

printf '10' > "$PS_DIR/config_ver.txt"   # 設定版本戳記(golive 判斷升級刷新用)
echo "[ok] Prime Stage 直式設定完成(macOS)"
