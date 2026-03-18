import { writable } from 'svelte/store';
import { WS } from '$lib/ws';

export interface Attachment {
    type: 'image';
    name: string;
    /** data:image/...;base64,... */
    dataUrl: string;
}

export interface Turn {
    role: 'user' | 'assistant';
    content: string;
    /** Frontend-only: attached images */
    attachments?: Attachment[];
    /** Frontend-only: was this a code response? */
    isCode?: boolean;
    /** Frontend-only: route label */
    route?: string;
    /** Frontend-only: pipeline metadata preserved per turn */
    plan?: Plan | null;
    specialistData?: SpecialistData | null;
    reflection?: Reflection | null;
    review?: ReviewResult | null;
    thinking?: string;
    draftThinking?: string;
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
    editing: boolean;
    warning: string;
    phase: 'idle' | 'routing' | 'planning' | 'consulting' | 'generating'
         | 'polishing' | 'validating' | 'fixing' | 'done';
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
    editing: false,
    warning: '',
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
                s.phase = 'planning';
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
                s.editing = !!data.editing;
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
            case 'polishing':
                s.phase = 'polishing';
                s.streamingThinking = '';
                break;
            case 'polished':
                // CSS was improved — replace streamingText with polished version
                if (data.code) {
                    s.streamingText = data.code;
                }
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
            case 'done': {
                s.phase = 'done';
                s.response = data.response || s.streamingText || '';
                s.thinking = data.thinking || s.streamingThinking || '';
                if (!s.draft) s.draft = data.draft || '';
                if (!s.draftThinking) s.draftThinking = data.draft_thinking || '';
                if (!s.route) s.route = data.route || '';
                if (!s.specialistData) s.specialistData = data.specialist_data || null;
                s.reflection = data.reflection;
                const codeRoute = s.route === 'ROUTE_DESIGN' || s.route === 'ROUTE_CODE';
                s.conversation = [
                    ...s.conversation,
                    {
                        role: 'assistant',
                        content: s.response,
                        isCode: codeRoute,
                        route: s.route,
                        plan: s.plan,
                        specialistData: s.specialistData,
                        reflection: s.reflection,
                        review: s.review,
                        thinking: s.thinking,
                        draftThinking: s.draftThinking,
                    },
                ];
                break;
            }
            case 'warning':
                s.warning = data.message || '';
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

export function sendThink(goal: string, attachments: Attachment[] = []) {
    let conv: Turn[] = [];
    const unsub = chat.subscribe((s) => { conv = s.conversation; });
    unsub();

    chat.update((s) => {
        s.conversation = [...s.conversation, {
            role: 'user', content: goal,
            attachments: attachments.length > 0 ? attachments : undefined,
        }];
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
        s.editing = false;
        s.warning = '';
        s.phase = 'routing';
        return s;
    });

    // Build conversation for backend — convert attachments to multimodal content
    const backendConv = conv.map(t => {
        if (t.attachments && t.attachments.length > 0) {
            const content: any[] = [{ type: 'text', text: t.content }];
            for (const att of t.attachments) {
                content.push({ type: 'image_url', image_url: { url: att.dataUrl } });
            }
            return { role: t.role, content };
        }
        return { role: t.role, content: t.content };
    });

    // Build current message content (may include images)
    let goalContent: any = goal;
    if (attachments.length > 0) {
        const parts: any[] = [{ type: 'text', text: goal }];
        for (const att of attachments) {
            parts.push({ type: 'image_url', image_url: { url: att.dataUrl } });
        }
        goalContent = parts;
    }

    ws?.send({
        type: 'think',
        goal: goalContent,
        conversation: backendConv,
    });
}
