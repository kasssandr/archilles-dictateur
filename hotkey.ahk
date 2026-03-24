; hotkey.ahk — Archilles Diktator AHK v2 Client
; Ctrl+Win hold = record, release = stop + transcribe + paste
#Requires AutoHotkey v2.0
#SingleInstance Force

; --- Configuration ---
global HOST := "127.0.0.1"
global PORT := 9876
global RECONNECT_INTERVAL := 5000  ; ms

; --- State ---
global sock := 0
global isConnected := false
global isRecording := false

; --- TCP Helpers ---

Connect() {
    global sock, isConnected
    try {
        sock := SocketCreate()
        SocketConnect(sock, HOST, PORT)
        isConnected := true
    } catch {
        isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
    }
}

TryReconnect() {
    if !isConnected
        Connect()
}

SocketCreate() {
    static ws2 := DllCall("LoadLibrary", "Str", "ws2_32", "Ptr")
    static wsaData := Buffer(408)
    static init := DllCall("ws2_32\WSAStartup", "UShort", 0x0202, "Ptr", wsaData)
    s := DllCall("ws2_32\socket", "Int", 2, "Int", 1, "Int", 6, "UInt")
    if s = 0xFFFFFFFF
        throw Error("socket() failed")
    return s
}

SocketConnect(s, host, port) {
    addr := Buffer(16, 0)
    NumPut("UShort", 2, addr, 0)  ; AF_INET
    NumPut("UShort", DllCall("ws2_32\htons", "UShort", port, "UShort"), addr, 2)
    NumPut("UInt", DllCall("ws2_32\inet_addr", "AStr", host, "UInt"), addr, 4)
    result := DllCall("ws2_32\connect", "UInt", s, "Ptr", addr, "Int", 16, "Int")
    if result != 0
        throw Error("connect() failed")
}

SendMsg(s, message) {
    encoded := Buffer(StrPut(message, "UTF-8") - 1)
    StrPut(message, encoded, "UTF-8")
    len := encoded.Size

    ; Length prefix (4 bytes big-endian)
    header := Buffer(4)
    NumPut("UChar", (len >> 24) & 0xFF, header, 0)
    NumPut("UChar", (len >> 16) & 0xFF, header, 1)
    NumPut("UChar", (len >> 8) & 0xFF, header, 2)
    NumPut("UChar", len & 0xFF, header, 3)

    DllCall("ws2_32\send", "UInt", s, "Ptr", header, "Int", 4, "Int", 0)
    DllCall("ws2_32\send", "UInt", s, "Ptr", encoded, "Int", len, "Int", 0)
}

RecvMsg(s) {
    ; Read 4-byte length header
    header := Buffer(4)
    bytesRead := DllCall("ws2_32\recv", "UInt", s, "Ptr", header, "Int", 4, "Int", 0, "Int")
    if bytesRead <= 0 {
        global isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
        return ""
    }

    len := (NumGet(header, 0, "UChar") << 24)
        | (NumGet(header, 1, "UChar") << 16)
        | (NumGet(header, 2, "UChar") << 8)
        | NumGet(header, 3, "UChar")

    if len = 0
        return ""

    data := Buffer(len)
    totalRead := 0
    while totalRead < len {
        n := DllCall("ws2_32\recv", "UInt", s, "Ptr", data.Ptr + totalRead, "Int", len - totalRead, "Int", 0, "Int")
        if n <= 0
            break
        totalRead += n
    }

    return StrGet(data, len, "UTF-8")
}

SocketClose(s) {
    DllCall("ws2_32\closesocket", "UInt", s)
}

; --- Hotkey: Ctrl+Win ---

; Key down: start recording
LAlt & LWin:: {
    global isRecording, isConnected, sock
    if isRecording || !isConnected
        return
    isRecording := true
    try {
        SendMsg(sock, "START")
    } catch {
        isRecording := false
        global isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
    }
}

; Key up: stop recording, receive text, paste
LAlt & LWin up:: {
    global isRecording, isConnected, sock
    if !isRecording
        return
    isRecording := false

    try {
        SendMsg(sock, "STOP")
        response := RecvMsg(sock)

        if SubStr(response, 1, 7) = "RESULT:" {
            text := SubStr(response, 8)
            if text != "" {
                A_Clipboard := text
                KeyWait("LAlt")
                KeyWait("LWin")
                Sleep(50)
                SendInput("^v")
            }
        }
    } catch {
        global isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
    }
}

; --- Startup ---
Connect()
