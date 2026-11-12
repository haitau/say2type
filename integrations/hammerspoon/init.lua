-- =====================================================================
-- say2type：双击 Control 全局语音输入热键
--
-- 手势：快速双击左/右 Ctrl → 开始录音；再双击一次 → 识别 + 清洗 + 粘贴
-- 原理：监听 flagsChanged，只统计“纯 Ctrl 点按”，普通按键（Ctrl+C 等）
--       会立即重置计数，因此不影响终端里任何 Ctrl 组合键。
-- 安装：~/.hammerspoon/init.lua 中 dofile 本文件，然后 reload Hammerspoon。
-- =====================================================================

local SAY2TYPE_BIN = "/Users/shawn/.local/bin/say2type"
local DOUBLE_TAP_INTERVAL = 0.5 -- 两次 Ctrl 点按的最大间隔（秒），对齐 macOS 双击标准
local CTRL_KEYCODES = {
  [59] = true, -- 左 Control（kVK_Control）
  [62] = true, -- 右 Control（kVK_RightControl）
}

-- 先启用 IPC，保证即使后续步骤失败也能用 `hs` 命令行排查
pcall(function()
  require("hs.ipc")
end)

local tapCount = 0
local resetTimer = nil
local busy = false
local menu = hs.menubar.new()

local function setRecordingUI(recording)
  if menu then
    menu:setTitle(recording and "🔴" or "")
  end
end

local function triggerSay2Type()
  if busy then
    hs.alert.show("say2type 正在处理中，请稍候…", 0.8)
    return
  end
  busy = true

  -- hs.task 的回调签名：(退出码, stdout, stderr)
  local task = hs.task.new(SAY2TYPE_BIN, function(code, _stdout, stderr)
    busy = false
    stderr = stderr or ""

    if code ~= 0 then
      setRecordingUI(false)
      hs.alert.show("⚠️ say2type 出错：" .. stderr, 3)
      return
    end

    if string.find(stderr, "开始后台录音", 1, true) then
      setRecordingUI(true)
      hs.alert.show("🎙️ 录音中…再双击 Ctrl 结束", 1)
      return
    end

    -- 第二次触发：识别 + 清洗 + 注入已在 CLI 内完成
    setRecordingUI(false)
    local finalText = string.match(stderr, "最终文本: (.+)")
    if string.find(stderr, "未识别到有效语音内容", 1, true) then
      hs.alert.show("没有听清，已取消", 1)
    elseif finalText and finalText ~= "" then
      hs.alert.show("✅ 已输入：" .. finalText, 1.5)
    else
      hs.alert.show("✅ 完成", 1)
    end
  end, { "once", "--toggle" })

  task:start()
end

-- 1) 监听修饰键变化，统计纯 Ctrl 点按
local flagsWatcher = hs.eventtap.new(
  { hs.eventtap.event.types.flagsChanged },
  function(event)
    local keyCode = event:getKeyCode()
    if not CTRL_KEYCODES[keyCode] then
      return false
    end
    local flags = event:getFlags()
    -- 仅在 Ctrl 按下、且没有同时按其他修饰键时计数（松开事件 flags.ctrl 为 nil）
    if flags.ctrl and not (flags.cmd or flags.alt or flags.shift or flags.fn) then
      tapCount = tapCount + 1
      if resetTimer then
        resetTimer:stop()
      end
      resetTimer = hs.timer.doAfter(DOUBLE_TAP_INTERVAL, function()
        tapCount = 0
      end)
      if tapCount >= 2 then
        tapCount = 0
        triggerSay2Type()
      end
    end
    return false -- 不吞掉事件，系统与其他 App 照常收到 Ctrl
  end
)

-- 2) 任何普通按键都会重置计数，保证 Ctrl+C / Ctrl+D 等组合键不会误触
local keyWatcher = hs.eventtap.new(
  { hs.eventtap.event.types.keyDown },
  function()
    tapCount = 0
    return false
  end
)

-- 事件监听需要「辅助功能」权限；未授权时给出明确提示而不是静默失败
local okFlags, errFlags = pcall(function()
  flagsWatcher:start()
  keyWatcher:start()
end)
if not okFlags then
  hs.alert.show(
    "say2type 无法启动热键监听：请在 系统设置 → 隐私与安全性 → 辅助功能 中授权 Hammerspoon。\n"
      .. tostring(errFlags),
    8
  )
end
setRecordingUI(false)

-- 可选：普通组合键调试入口（双击不灵敏时先用它验证链路）。
-- 需要启用就取消注释：
-- hs.hotkey.bind({ "cmd", "alt", "ctrl" }, "V", triggerSay2Type)

-- 看门狗：TCC 状态变化等原因可能导致 eventtap 静默失效，定时检查并自动恢复
local watchdog = hs.timer.doEvery(5, function()
  if not flagsWatcher:isEnabled() or not keyWatcher:isEnabled() then
    pcall(function()
      flagsWatcher:start()
      keyWatcher:start()
    end)
    hs.alert.show("say2type 热键监听器已自动重启", 2)
  end
end)

-- 调试入口：
--   hs -c "say2typeTrigger()"            模拟一次双击触发
--   hs -c "say2typeDebug()"              查看监听器状态与当前计数
_G.say2typeTrigger = triggerSay2Type
_G.say2typeDebug = function()
  return string.format(
    "flagsWatcher=%s keyWatcher=%s tapCount=%d",
    tostring(flagsWatcher:isEnabled()),
    tostring(keyWatcher:isEnabled()),
    tapCount
  )
end

hs.alert.show("say2type 热键已加载：双击 Ctrl 开始/结束录音", 2)
