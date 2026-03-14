type EventHandler = (data: Record<string, any>) => void;

export class WS {
    private socket: WebSocket | null = null;
    private handler: EventHandler;
    private url: string;

    constructor(url: string, handler: EventHandler) {
        this.url = url;
        this.handler = handler;
    }

    connect() {
        this.socket = new WebSocket(this.url);
        this.socket.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                this.handler(data);
            } catch { /* ignore parse errors */ }
        };
        this.socket.onclose = () => {
            this.socket = null;
        };
    }

    send(msg: Record<string, any>) {
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(msg));
        }
    }

    disconnect() {
        this.socket?.close();
        this.socket = null;
    }

    get connected(): boolean {
        return this.socket?.readyState === WebSocket.OPEN;
    }
}
