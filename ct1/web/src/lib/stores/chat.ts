import { writable, get } from 'svelte/store';
import { WS } from '$lib/ws';
import { preferences } from '$lib/stores/preferences';

export interface Attachment {
    type: 'image' | 'file';
    name: string;
    /** data:image/...;base64,... — only for images */
    dataUrl: string;
    /** text content — only for text files */
    textContent?: string;
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
    messageId?: string;
    feedback?: number;
    fetchedContent?: { url: string; title: string; content: string;
                       contentLength: number; truncated: boolean }[];
}

export interface Reflection {
    self_score: number;
    lesson: string;
    [key: string]: any;
}

export interface SpecialistData {
    _route?: string;
    // ROUTE_DESIGN
    project_type?: string;
    audience?: string;
    mood?: string[];
    theme?: string;
    sections?: string[];
    color_hints?: string[];
    special?: string[];
    // ROUTE_CODE
    language?: string;
    type?: string;
    requirements?: string[];
    edge_cases?: string[];
    output_format?: string;
    // ROUTE_COMPUTER
    framework?: string;
    files?: string[];
    run_command?: string;
    // ROUTE_DIRECT
    topic?: string;
    answer_type?: string;
    depth?: string;
    key_points?: string[];
    // Legacy
    palette?: Record<string, string>;
    typography?: Record<string, string>;
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

export type ModeOverride = 'auto' | 'design' | 'code' | 'chat' | 'computer';

interface ChatState {
    conversationId: string | null;
    conversation: Turn[];
    events: Record<string, any>[];
    route: string;
    plan: Plan | null;
    specialistData: SpecialistData | null;

    review: ReviewResult | null;
    reflection: Reflection | null;
    response: string;
    thinking: string;
    draft: string;
    draftThinking: string;
    streamingText: string;
    streamingThinking: string;
    checklist: { item: string; done: boolean }[];
    validationIssues: string[];
    editing: boolean;
    warning: string;
    modeOverride: ModeOverride;
    undoStack: string[];
    terminalOutput: string;
    workspaceId: string | null;
    phase: 'idle' | 'routing' | 'planning' | 'generating'
         | 'polishing' | 'refining' | 'validating' | 'fixing' | 'done'
         | 'spec_generating' | 'spec_validated'
         | 'component_generating' | 'component_validating'
         | 'assembling';
    designSpec: Record<string, any> | null;
    componentProgress: {
        id: string;
        index: number;
        total: number;
        status: 'generating' | 'validated' | 'patching' | 'fallback';
    }[];
    tokenCount: number;
    genStartTime: number;
    tokensPerSec: number;
    savedFiles: string[];
    fetchingUrls: { url: string; status: 'fetching' | 'done' | 'failed'; error?: string }[];
    fetchedContent: { url: string; title: string; content: string;
                      contentLength: number; truncated: boolean }[];
}

const initial: ChatState = {
    conversationId: null,
    conversation: [],
    events: [],
    route: '',
    plan: null,
    specialistData: null,

    review: null,
    reflection: null,
    response: '',
    thinking: '',
    draft: '',
    draftThinking: '',
    streamingText: '',
    streamingThinking: '',
    checklist: [],
    validationIssues: [],
    editing: false,
    warning: '',
    modeOverride: 'auto',
    undoStack: [],
    terminalOutput: '',
    workspaceId: null,
    phase: 'idle',
    designSpec: null,
    componentProgress: [],
    tokenCount: 0,
    genStartTime: 0,
    tokensPerSec: 0,
    savedFiles: [],
    fetchingUrls: [],
    fetchedContent: [],
};

export const chat = writable<ChatState>({ ...initial });

let ws: WS | null = null;

function handleEvent(data: Record<string, any>) {
    chat.update((s) => {
        s.events = [...s.events, data];

        switch (data.event) {
            case 'conversation_id':
                s.conversationId = data.id;
                break;
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
            case 'generating':
                s.phase = 'generating';
                s.editing = !!data.editing;
                // Push previous code to undo stack before edit overwrites it
                if (s.editing && s.conversation.length > 0) {
                    const lastAssistant = [...s.conversation].reverse().find(t => t.role === 'assistant' && t.isCode);
                    if (lastAssistant) {
                        s.undoStack = [...s.undoStack.slice(-4), lastAssistant.content];
                    }
                }
                s.streamingText = '';
                s.streamingThinking = '';
                s.tokenCount = 0;
                s.genStartTime = Date.now();
                s.tokensPerSec = 0;
                break;
            case 'token':
                if (data.kind === 'thinking') {
                    s.streamingThinking += data.text;
                } else {
                    s.streamingText += data.text;
                }
                s.tokenCount++;
                if (s.genStartTime) {
                    const elapsed = (Date.now() - s.genStartTime) / 1000;
                    if (elapsed > 0.5) {
                        s.tokensPerSec = Math.round(s.tokenCount / elapsed);
                    }
                }
                break;
            case 'draft':
                s.draft = data.text;
                s.draftThinking = data.thinking || '';
                break;
            case 'checklist':
                s.checklist = data.items || [];
                break;
            case 'polishing':
                s.phase = 'polishing';
                s.streamingThinking = '';
                break;
            case 'refining':
                s.phase = 'refining';
                // Keep streamingText visible (shows draft in preview)
                // Refined output will replace it via 'polished' event
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
                // If stopGeneration already committed the partial turn, skip
                const lastTurn = s.conversation[s.conversation.length - 1];
                if (s.phase === 'done' && lastTurn?.role === 'assistant') {
                    break;
                }
                s.phase = 'done';
                s.response = data.response || s.streamingText || '';
                s.thinking = data.thinking || s.streamingThinking || '';
                s.streamingThinking = '';
                s.streamingText = '';
                if (s.genStartTime && s.tokenCount > 0) {
                    const elapsed = (Date.now() - s.genStartTime) / 1000;
                    s.tokensPerSec = elapsed > 0 ? Math.round(s.tokenCount / elapsed) : 0;
                }
                if (!s.draft) s.draft = data.draft || '';
                if (!s.draftThinking) s.draftThinking = data.draft_thinking || '';
                if (!s.route) s.route = data.route || '';
                if (!s.specialistData) s.specialistData = data.specialist_data || null;
                s.reflection = data.reflection;
                const codeRoute = s.route === 'ROUTE_DESIGN' || s.route === 'ROUTE_CODE' || s.route === 'ROUTE_COMPUTER';
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
                        fetchedContent: s.fetchedContent.length > 0 ? s.fetchedContent : undefined,
                    },
                ];
                break;
            }
            // ── Precision-Design pipeline events ──
            case 'spec_generating':
                s.phase = 'spec_generating';
                s.componentProgress = [];
                s.designSpec = null;
                s.streamingText = '';
                s.streamingThinking = '';
                s.tokenCount = 0;
                s.genStartTime = Date.now();
                s.tokensPerSec = 0;
                break;
            case 'spec_validated':
                s.phase = 'spec_validated';
                s.designSpec = data.spec || null;
                break;
            case 'spec_failed':
                s.warning = `Spec validation failed: ${(data.errors || []).join(', ')}`;
                break;
            case 'component_generating': {
                s.phase = 'component_generating';
                const cid = data.component_id;
                const idx = data.index ?? 0;
                const total = data.total ?? 0;
                const existing = s.componentProgress.findIndex(c => c.id === cid);
                if (existing >= 0) {
                    s.componentProgress[existing] = { id: cid, index: idx, total, status: 'generating' };
                } else {
                    s.componentProgress = [...s.componentProgress, { id: cid, index: idx, total, status: 'generating' }];
                }
                break;
            }
            case 'component_validated': {
                const cvid = data.component_id;
                const cidx = s.componentProgress.findIndex(c => c.id === cvid);
                if (cidx >= 0) {
                    s.componentProgress[cidx] = { ...s.componentProgress[cidx], status: 'validated' };
                }
                break;
            }
            case 'component_patching': {
                const cpid = data.component_id;
                const cpidx = s.componentProgress.findIndex(c => c.id === cpid);
                if (cpidx >= 0) {
                    s.componentProgress[cpidx] = { ...s.componentProgress[cpidx], status: 'patching' };
                }
                break;
            }
            case 'component_fallback': {
                const cfid = data.component_id;
                const cfidx = s.componentProgress.findIndex(c => c.id === cfid);
                if (cfidx >= 0) {
                    s.componentProgress[cfidx] = { ...s.componentProgress[cfidx], status: 'fallback' };
                }
                break;
            }
            case 'assembling':
                s.phase = 'assembling';
                s.streamingText = '';
                break;
            case 'retrying':
                s.phase = 'fixing';
                s.warning = data.message || 'Retrying broken sections...';
                s.streamingText = '';
                s.streamingThinking = '';
                break;
            case 'file_saved':
                // Computer mode: file written to workspace
                if (data.path && !s.savedFiles.includes(data.path)) {
                    s.savedFiles = [...s.savedFiles, data.path];
                }
                break;
            case 'terminal_output':
                // Computer mode: command execution output
                s.terminalOutput += data.text || '';
                break;
            case 'url_fetching':
                s.fetchingUrls = [...s.fetchingUrls, { url: data.url, status: 'fetching' }];
                break;
            case 'url_fetched': {
                s.fetchingUrls = s.fetchingUrls.map(f =>
                    f.url === data.url ? { ...f, status: 'done' as const } : f
                );
                s.fetchedContent = [...s.fetchedContent, {
                    url: data.url,
                    title: data.title || '',
                    content: data.preview || '',
                    contentLength: data.content_length || 0,
                    truncated: data.truncated || false,
                }];
                break;
            }
            case 'url_failed':
                s.fetchingUrls = s.fetchingUrls.map(f =>
                    f.url === data.url ? { ...f, status: 'failed' as const, error: data.error } : f
                );
                break;
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

export function loadFromHistory(conv: {
    id: string;
    messages: Array<{
        id?: string;
        role: string;
        content: string;
        thinking?: string;
        draft?: string;
        route?: string;
        specialist_data?: string;
        reflection?: string;
        feedback?: number;
    }>;
}) {
    chat.update((s) => {
        s.conversationId = conv.id;
        s.conversation = conv.messages.map((m) => {
            const route = m.route || undefined;
            // Derive isCode from route, or detect HTML for old messages without route
            const isCode = route === 'ROUTE_DESIGN' || route === 'ROUTE_CODE' || route === 'ROUTE_COMPUTER'
                || (m.role === 'assistant' && /^<!doctype\s/i.test(m.content.trim()));

            // Safe JSON parsing — malformed data must not crash the load
            let specialistData;
            try { specialistData = m.specialist_data ? JSON.parse(m.specialist_data) : undefined; }
            catch { specialistData = undefined; }

            let reflection;
            try { reflection = m.reflection ? JSON.parse(m.reflection) : undefined; }
            catch { reflection = undefined; }

            return {
                role: m.role as 'user' | 'assistant',
                content: m.content,
                messageId: m.id,
                thinking: m.thinking || undefined,
                route,
                isCode,
                specialistData,
                reflection,
                feedback: m.feedback,
            };
        });
        s.phase = 'idle';
        s.events = [];
        s.route = '';
        s.plan = null;
        s.specialistData = null;
        s.review = null;
        s.reflection = null;
        s.response = '';
        s.thinking = '';
        s.draft = '';
        s.draftThinking = '';
        s.streamingText = '';
        s.streamingThinking = '';
        s.validationIssues = [];
        s.editing = false;
        s.warning = '';
        s.undoStack = [];
        return s;
    });
}

export function newConversation() {
    chat.set({ ...initial });
}

export function setMode(mode: ModeOverride) {
    chat.update((s) => { s.modeOverride = mode; return s; });
}

export function undo() {
    chat.update((s) => {
        if (s.undoStack.length === 0) return s;
        const prev = s.undoStack[s.undoStack.length - 1];
        s.undoStack = s.undoStack.slice(0, -1);
        // Replace last assistant code turn with previous version
        for (let i = s.conversation.length - 1; i >= 0; i--) {
            if (s.conversation[i].role === 'assistant' && s.conversation[i].isCode) {
                s.conversation = [...s.conversation];
                s.conversation[i] = { ...s.conversation[i], content: prev };
                break;
            }
        }
        s.response = prev;
        return s;
    });
}

export async function setFeedback(turnIndex: number, feedback: number) {
    let messageId: string | undefined;
    const unsub = chat.subscribe((s) => {
        messageId = s.conversation[turnIndex]?.messageId;
    });
    unsub();

    if (messageId) {
        await fetch(`/api/messages/${messageId}/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback }),
        });
    }

    chat.update((s) => {
        if (s.conversation[turnIndex]) {
            s.conversation[turnIndex].feedback = feedback;
        }
        return s;
    });
}

export function regenerate() {
    let lastUserMsg = '';
    let lastAttachments: Attachment[] = [];

    chat.update((s) => {
        // Remove last assistant turn
        if (s.conversation.length >= 1 && s.conversation[s.conversation.length - 1].role === 'assistant') {
            s.conversation = s.conversation.slice(0, -1);
        }
        // Get and remove last user turn
        const lastUser = s.conversation[s.conversation.length - 1];
        if (lastUser && lastUser.role === 'user') {
            lastUserMsg = lastUser.content;
            lastAttachments = lastUser.attachments || [];
            s.conversation = s.conversation.slice(0, -1);
        }
        return s;
    });

    if (lastUserMsg) {
        sendThink(lastUserMsg, lastAttachments);
    }
}

export function setWorkspaceId(id: string) {
    chat.update((s) => { s.workspaceId = id; return s; });
}

export function stopGeneration() {
    ws?.send({ type: 'cancel' });
    chat.update((s) => {
        const partial = s.streamingText || '';
        s.thinking = s.streamingThinking || '';

        if (!partial && s.conversation.length > 0 && s.conversation[s.conversation.length - 1].role === 'user') {
            // Nothing generated yet — remove the user turn, go back to idle
            s.conversation = s.conversation.slice(0, -1);
            s.phase = 'idle';
        } else if (partial) {
            // Push partial response as a real assistant turn so it stays
            // in history with feedback + regenerate buttons
            const codeRoute = s.route === 'ROUTE_DESIGN' || s.route === 'ROUTE_CODE' || s.route === 'ROUTE_COMPUTER';
            s.conversation = [
                ...s.conversation,
                {
                    role: 'assistant',
                    content: partial,
                    isCode: codeRoute,
                    route: s.route,
                    plan: s.plan,
                    specialistData: s.specialistData,
                    thinking: s.thinking,
                    draftThinking: s.draftThinking,
                    fetchedContent: s.fetchedContent.length > 0 ? s.fetchedContent : undefined,
                },
            ];
            s.response = partial;
            s.phase = 'done';
        } else {
            s.phase = 'idle';
        }

        // Reset streaming state
        s.streamingText = '';
        s.streamingThinking = '';
        return s;
    });
}

export function sendThink(goal: string, attachments: Attachment[] = []) {
    let conv: Turn[] = [];
    let mode: ModeOverride = 'auto';
    let wsId: string | null = null;
    const unsub = chat.subscribe((s) => { conv = s.conversation; mode = s.modeOverride; wsId = s.workspaceId; });
    unsub();

    let convId: string | null = null;
    const unsub2 = chat.subscribe((s) => { convId = s.conversationId; });
    unsub2();

    chat.update((s) => {
        s.conversation = [...s.conversation, {
            role: 'user', content: goal,
            attachments: attachments.length > 0 ? attachments : undefined,
        }];
        s.events = [];
        s.route = '';
        s.plan = null;
        s.specialistData = null;
        s.review = null;
        s.reflection = null;
        s.response = '';
        s.thinking = '';
        s.draft = '';
        s.draftThinking = '';
        s.checklist = [];
        s.validationIssues = [];
        s.streamingText = '';
        s.streamingThinking = '';
        s.editing = false;
        s.warning = '';
        s.phase = 'routing';
        s.tokenCount = 0;
        s.genStartTime = 0;
        s.tokensPerSec = 0;
        s.savedFiles = [];
        s.fetchingUrls = [];
        s.fetchedContent = [];
        return s;
    });

    // Build conversation for backend — convert attachments to multimodal content
    const backendConv = conv.map(t => {
        if (t.attachments && t.attachments.length > 0) {
            let text = t.content;
            const images: Attachment[] = [];
            for (const att of t.attachments) {
                if (att.type === 'file' && att.textContent) {
                    text = `[File: ${att.name}]\n${att.textContent}\n\n${text}`;
                } else if (att.type === 'image') {
                    images.push(att);
                }
            }
            if (images.length > 0) {
                const content: any[] = [{ type: 'text', text }];
                for (const att of images) {
                    content.push({ type: 'image_url', image_url: { url: att.dataUrl } });
                }
                return { role: t.role, content };
            }
            return { role: t.role, content: text };
        }
        return { role: t.role, content: t.content };
    });

    // Build current message content (may include images and text files)
    let textPrefix = '';
    const imageAtts: Attachment[] = [];
    for (const att of attachments) {
        if (att.type === 'file' && att.textContent) {
            textPrefix += `[File: ${att.name}]\n${att.textContent}\n\n`;
        } else if (att.type === 'image') {
            imageAtts.push(att);
        }
    }

    const fullGoal = textPrefix ? `${textPrefix}${goal}` : goal;

    let goalContent: any = fullGoal;
    if (imageAtts.length > 0) {
        const parts: any[] = [{ type: 'text', text: fullGoal }];
        for (const att of imageAtts) {
            parts.push({ type: 'image_url', image_url: { url: att.dataUrl } });
        }
        goalContent = parts;
    }

    const prefs = get(preferences);
    ws?.send({
        type: 'think',
        goal: goalContent,
        conversation: backendConv,
        conversation_id: convId,
        position: conv.length,
        ...(mode !== 'auto' ? { mode_override: mode } : {}),
        ...(wsId ? { workspace_id: wsId } : {}),
        ...(!prefs.designRefinement ? { skip_refinement: true } : {}),
    });
}
