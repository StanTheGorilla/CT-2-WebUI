import { writable } from 'svelte/store';
import { WS } from '$lib/ws';

export interface Turn {
    role: 'user' | 'assistant';
    content: string;
}

export interface MindTurn {
    name: string;
    round: number;
    text: string;
}

export interface Intent {
    task_type: string;
    what_to_produce: string;
    requirements: string[];
    complexity: string;
}

export interface Reflection {
    self_score: number;
    lesson: string;
    rounds: number;
    [key: string]: any;
}

interface ChatState {
    conversation: Turn[];
    events: Record<string, any>[];
    dialogue: MindTurn[];
    intent: Intent | null;
    reflection: Reflection | null;
    response: string;
    phase: 'idle' | 'framing' | 'deliberating' | 'synthesizing' | 'done';
    currentRound: number;
}

const initial: ChatState = {
    conversation: [],
    events: [],
    dialogue: [],
    intent: null,
    reflection: null,
    response: '',
    phase: 'idle',
    currentRound: 0,
};

export const chat = writable<ChatState>({ ...initial });

let ws: WS | null = null;

function handleEvent(data: Record<string, any>) {
    chat.update((s) => {
        s.events = [...s.events, data];

        switch (data.event) {
            case 'framing':
                s.phase = 'framing';
                break;
            case 'framed':
                s.phase = 'deliberating';
                s.intent = {
                    task_type: data.task_type,
                    what_to_produce: data.what_to_produce || data.text,
                    requirements: data.requirements || [],
                    complexity: data.complexity,
                };
                break;
            case 'round_start':
                s.currentRound = data.round_num;
                break;
            case 'mind_turn':
                s.dialogue = [...s.dialogue, {
                    name: data.name,
                    round: s.currentRound,
                    text: data.text,
                }];
                break;
            case 'tension':
                // Tension events are informational — shown in the deliberation panel
                break;
            case 'converging':
                // Converging — deliberation wrapping up
                break;
            case 'synthesizing':
                s.phase = 'synthesizing';
                break;
            case 'done':
                s.phase = 'done';
                s.response = data.response;
                s.reflection = data.reflection;
                s.conversation = [
                    ...s.conversation,
                    { role: 'assistant', content: data.response },
                ];
                break;
        }
        return s;
    });
}

export function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/think`;
    ws = new WS(url, handleEvent);
    ws.connect();
}

export function disconnect() {
    ws?.disconnect();
    ws = null;
}

export function sendThink(goal: string) {
    let conv: Turn[] = [];
    const unsub = chat.subscribe((s) => { conv = s.conversation; });
    unsub();

    chat.update((s) => {
        s.conversation = [...s.conversation, { role: 'user', content: goal }];
        s.events = [];
        s.dialogue = [];
        s.intent = null;
        s.reflection = null;
        s.response = '';
        s.phase = 'framing';
        s.currentRound = 0;
        return s;
    });

    ws?.send({
        type: 'think',
        goal,
        conversation: conv,
    });
}
