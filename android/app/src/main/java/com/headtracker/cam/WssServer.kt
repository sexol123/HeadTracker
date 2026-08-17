package com.headtracker.cam

import org.java_websocket.WebSocket
import org.java_websocket.handshake.ClientHandshake
import org.java_websocket.server.WebSocketServer
import java.net.InetSocketAddress

/**
 * WebSocket server on the phone. Pushes raw binary MJPEG frames to every
 * connected client — the desktop's WebSocketCamera decodes them directly
 * with cv2.imdecode, no base64 overhead.
 */
class WssServer(port: Int, private val onClientsChanged: (Int) -> Unit) :
    WebSocketServer(InetSocketAddress(port)) {

    init {
        setConnectionLostTimeout(30)
        try {
            setTcpNoDelay(true)
        } catch (_: Exception) {
        }
    }

    override fun onOpen(conn: WebSocket, handshake: ClientHandshake) {
        onClientsChanged(connections.size)
    }

    override fun onClose(conn: WebSocket, code: Int, reason: String, remote: Boolean) {
        onClientsChanged(connections.size)
    }

    override fun onMessage(conn: WebSocket, message: String) = Unit

    override fun onError(conn: WebSocket?, ex: Exception) = Unit

    override fun onStart() = Unit

    /** Send one JPEG frame to every connected client. */
    fun broadcastFrame(frame: ByteArray) {
        for (conn in connections) {
            try {
                if (conn.isOpen) conn.send(frame)
            } catch (_: Exception) {
            }
        }
    }
}