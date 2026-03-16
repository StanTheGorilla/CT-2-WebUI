import { writable } from 'svelte/store';
import { WS } from '$lib/ws';

export interface Turn {
    role: 'user' | 'assistant';
    content: string;
}

export interface Reflection {
    self_score: number;
    lesson: string;
    [key: string]: any;
}

export interface SpecialistData {
    palette?: Record<string, string>;
    typography?: Record<string, string>;
    sections?: string[];
    rationale?: string;
}

export interface ReviewResult {
    pass: boolean;
    critical_issues: string[];
    fix_instructions: string;
}

export interface PlanComponent {
    id: number;
    name: string;
    description: string;
}

export interface Plan {
    output_type: string;
    components: PlanComponent[];
    complexity: string;
}

interface ChatState {
    conversation: Turn[];
    events: Record<string, any>[];
    route: string;
    plan: Plan | null;
    specialistData: SpecialistData | null;
    specialistStream: string;
    review: ReviewResult | null;
    reflection: Reflection | null;
    response: string;
    thinking: string;
    draft: string;
    draftThinking: string;
    streamingText: string;
    streamingThinking: string;
    validationIssues: string[];
    phase: 'idle' | 'routing' | 'planning' | 'consulting' | 'generating'
         | 'validating' | 'fixing' | 'done';
}

const initial: ChatState = {
    conversation: [],
    events: [],
    route: '',
    plan: null,
    specialistData: null,
    specialistStream: '',
    review: null,
    reflection: null,
    response: '',
    thinking: '',
    draft: '',
    draftThinking: '',
    streamingText: '',
    streamingThinking: '',
    validationIssues: [],
    phase: 'idle',
};

export const chat = writable<ChatState>({ ...initial });

let ws: WS | null = null;

function handleEvent(data: Record<string, any>) {
    chat.update((s) => {
        s.events = [...s.events, data];

        switch (data.event) {
            case 'routing':
                s.phase = 'routing';
                break;
            case 'routed':
                s.route = data.route;
                break;
            case 'planned':
                s.phase = 'planning';
                s.plan = data.plan || null;
                break;
            case 'consulting':
                s.phase = 'consulting';
                s.specialistStream = '';
                break;
            case 'specialist_token':
                s.specialistStream += data.text;
                break;
            case 'consulted':
                s.specialistData = data.data || null;
                break;
            case 'generating':
                s.phase = 'generating';
                s.streamingText = '';
                s.streamingThinking = '';
                break;
            case 'token':
                if (data.kind === 'thinking') {
                    s.streamingThinking += data.text;
                } else {
                    s.streamingText += data.text;
                }
                break;
            case 'draft':
                s.draft = data.text;
                s.draftThinking = data.thinking || '';
                break;
            case 'validating':
                s.phase = 'validating';
                s.validationIssues = data.issues || [];
                s.review = data.review || null;
                break;
            case 'validated':
                s.validationIssues = [];
                s.review = data.review || null;
                break;
            case 'fixing':
                s.phase = 'fixing';
                s.streamingText = '';
                s.streamingThinking = '';
                break;
            case 'done':
                s.phase = 'done';
                // Use the done event's response, but fall back to
                // accumulated streaming text so the user always sees output
                s.response = data.response || s.streamingText || '';
                s.thinking = data.thinking || s.streamingThinking || '';
                if (!s.draft) s.draft = data.draft || '';
                if (!s.draftThinking) s.draftThinking = data.draft_thinking || '';
                if (!s.route) s.route = data.route || '';
                if (!s.specialistData) s.specialistData = data.specialist_data || null;
                s.reflection = data.reflection;
                s.conversation = [
                    ...s.conversation,
                    { role: 'assistant', content: s.response },
                ];
                break;
            case 'error':
                s.phase = 'done';
                s.response = `**Error:** ${data.message || 'Unknown error'}`;
                break;
        }
        return s;
    });
}

type ConnectCallback = () => void;

export function connect(onConnected?: ConnectCallback) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/think`;
    ws = new WS(url, handleEvent);
    if (onConnected) ws.onOpen = onConnected;
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
        s.route = '';
        s.plan = null;
        s.specialistData = null;
        s.specialistStream = '';
        s.review = null;
        s.reflection = null;
        s.response = '';
        s.thinking = '';
        s.draft = '';
        s.draftThinking = '';
        s.validationIssues = [];
        s.streamingText = '';
        s.streamingThinking = '';
        s.phase = 'routing';
        return s;
    });

    ws?.send({
        type: 'think',
        goal,
        conversation: conv,
    });
}
