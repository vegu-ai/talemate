import { describe, it, expect, beforeEach } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import { ASK_AGENTS, askAgent, askAgentRequests, takePendingPrompt } from "@/utils/askAgent";

function read(path) {
    return readSource(fileURLToPath(new URL(path, import.meta.url)));
}

const ASK_AGENT = read("../../src/components/AskAgent.vue");
const DIRECTOR_CHATS = read("../../src/components/DirectorConsoleChats.vue");
const HELP_CHAT = read("../../src/components/HelpChat.vue");

// drain whatever an earlier spec left pending, so each test starts empty
beforeEach(() => {
    takePendingPrompt("director");
    takePendingPrompt("help");
});

describe("askAgent store", () => {
    it("hands the prompt to one taker only", () => {
        expect(askAgent("director", "set up perspectives")).toBe(true);
        expect(takePendingPrompt("director")).toBe("set up perspectives");
        expect(takePendingPrompt("director")).toBeNull();
    });

    it("counts every ask, so a taker can watch without racing another one", () => {
        const before = askAgentRequests("help");
        askAgent("help", "explain this setting");
        askAgent("help", "explain that setting");
        expect(askAgentRequests("help")).toBe(before + 2);
        // the counter survives the take that clears the prompt
        expect(takePendingPrompt("help")).toBe("explain that setting");
        expect(askAgentRequests("help")).toBe(before + 2);
    });

    it("keeps the two agents apart", () => {
        askAgent("director", "director prompt");
        expect(takePendingPrompt("help")).toBeNull();
        expect(takePendingPrompt("director")).toBe("director prompt");
    });

    it("refuses an unknown agent and an empty prompt", () => {
        const requests = askAgentRequests("director");
        expect(askAgent("narrator", "hello")).toBe(false);
        expect(askAgent("director", "")).toBe(false);
        expect(askAgentRequests("director")).toBe(requests);
        expect(takePendingPrompt("director")).toBeNull();
    });

    it("refuses an agent named after an Object.prototype member", () => {
        for(const name of ["constructor", "toString", "hasOwnProperty", "__proto__"]) {
            expect(askAgent(name, "hello"), name).toBe(false);
            expect(askAgentRequests(name), name).toBe(0);
            expect(takePendingPrompt(name), name).toBeNull();
        }
    });
});

function askAgentStub(agent, { prompt = "a prompt" } = {}) {
    const opened = [];
    const stub = {
        agent,
        prompt,
        openDirectorConsole: () => opened.push("director"),
        openHelpChat: () => opened.push("help"),
        opened,
    };
    stub.ask = lift(ASK_AGENT, "ask", "AskAgent.vue", { askAgent }).bind(stub);
    return stub;
}

describe("AskAgent.ask", () => {
    it("stores the prompt before it opens the director drawer", () => {
        const stub = askAgentStub("director", { prompt: "set up perspectives" });
        stub.ask();
        expect(stub.opened).toEqual(["director"]);
        expect(takePendingPrompt("director")).toBe("set up perspectives");
    });

    it("opens the help drawer for the help agent", () => {
        const stub = askAgentStub("help", { prompt: "explain this setting" });
        stub.ask();
        expect(stub.opened).toEqual(["help"]);
        expect(takePendingPrompt("help")).toBe("explain this setting");
    });

    it("opens no drawer when there is nothing to ask", () => {
        const stub = askAgentStub("director", { prompt: "" });
        stub.ask();
        expect(stub.opened).toEqual([]);
    });

    it("names an icon for every agent it accepts", () => {
        for(const agent of Object.keys(ASK_AGENTS)) {
            expect(ASK_AGENTS[agent].icon).toMatch(/^mdi-/);
        }
    });
});

// the chat components share this shape: take the prompt, create a chat, and
// send the prompt once the backend confirms that chat's history
function chatStub(source, label) {
    const stub = {
        askAgentPrompt: null,
        askAgentChatId: null,
        activeChatId: null,
        chats: [],
        chatMessages: [],
        chatInput: "",
        tokenTotal: null,
        activePlan: null,
        sceneAware: false,
        isProcessing: false,
        currentChatMode: "normal",
        confirmWriteActions: true,
        budgets: null,
        created: 0,
        historyRequests: [],
        sent: [],
        createChat() { stub.created += 1; },
        sendChat() { stub.sent.push(stub.chatInput); stub.chatInput = ""; },
        // the components name their own history request differently
        onSelectChat() { stub.historyRequests.push(stub.activeChatId); },
        requestChatHistory() { stub.historyRequests.push(stub.activeChatId); },
        selectChat(chatId) { stub.activeChatId = chatId; },
        resetChatForNewScene() {},
        removeTrailingPlaceholder() {},
        ensureTrailingPlaceholder() {},
        applyChatAppend() {},
        addOrUpdateConfirmRequest() {},
        markConfirmRequestDecision() {},
    };
    stub.startAskAgentChat = lift(source, "startAskAgentChat", label, { takePendingPrompt }).bind(stub);
    stub.sendAskAgentPrompt = lift(source, "sendAskAgentPrompt", label).bind(stub);
    stub.handleMessage = lift(source, "handleMessage", label).bind(stub);
    return stub;
}

// the frames the backend queues for a newly created chat, in order
function chatCreated(type, chatId) {
    return { type, action: "chat_created", chat_id: chatId, chat_list: [{ id: chatId }] };
}

function chatHistory(type, chatId, messages = []) {
    return { type, action: "chat_history", chat_id: chatId, messages };
}

describe.each([
    ["DirectorConsoleChats.vue", DIRECTOR_CHATS, "director"],
    ["HelpChat.vue", HELP_CHAT, "help"],
])("%s consumes a pending prompt", (label, source, agent) => {
    it("creates a chat and sends the prompt when that chat is confirmed", () => {
        askAgent(agent, "set up perspectives");
        const stub = chatStub(source, label);
        stub.startAskAgentChat();
        expect(stub.created).toBe(1);
        expect(stub.sent).toEqual([]);
        stub.handleMessage(chatCreated(agent, "chat-b"));
        stub.handleMessage(chatHistory(agent, "chat-b"));
        expect(stub.sent).toEqual(["set up perspectives"]);
    });

    it("does nothing without a pending prompt", () => {
        const stub = chatStub(source, label);
        stub.startAskAgentChat();
        expect(stub.created).toBe(0);
        stub.sendAskAgentPrompt("chat-b");
        expect(stub.sent).toEqual([]);
    });

    it("sends the prompt once, so a second chat does not repeat it", () => {
        askAgent(agent, "set up perspectives");
        const stub = chatStub(source, label);
        stub.startAskAgentChat();
        stub.askAgentChatId = "chat-b";
        stub.sendAskAgentPrompt("chat-b");
        stub.sendAskAgentPrompt("chat-b");
        expect(stub.sent).toEqual(["set up perspectives"]);
    });

    it("sends into the chat it created, not into a history frame already in flight", () => {
        // chat_done requests the history of chat A after every completed turn,
        // so one is in flight when the action is clicked
        const stub = chatStub(source, label);
        stub.activeChatId = "chat-a";
        askAgent(agent, "set up perspectives");
        stub.startAskAgentChat();
        stub.handleMessage(chatHistory(agent, "chat-a", [{ source: agent, message: "earlier" }]));
        expect(stub.sent).toEqual([]);

        stub.handleMessage(chatCreated(agent, "chat-b"));
        expect(stub.askAgentChatId).toBe("chat-b");
        // the chat it created carries no history request of its own
        expect(stub.historyRequests).toEqual([]);
        stub.handleMessage(chatHistory(agent, "chat-b"));
        expect(stub.sent).toEqual(["set up perspectives"]);
    });

    it("refuses a second ask while the first chat is still coming up", () => {
        const stub = chatStub(source, label);
        askAgent(agent, "first ask");
        stub.startAskAgentChat();
        askAgent(agent, "second ask");
        stub.startAskAgentChat();
        expect(stub.created).toBe(1);
        // the refused ask is taken off the store, so no later mount replays it
        expect(takePendingPrompt(agent)).toBeNull();

        stub.handleMessage(chatCreated(agent, "chat-b"));
        stub.handleMessage(chatHistory(agent, "chat-b"));
        expect(stub.sent).toEqual(["first ask"]);
    });

    it("requests its own history for a chat nobody asked for", () => {
        const stub = chatStub(source, label);
        stub.handleMessage(chatCreated(agent, "chat-b"));
        expect(stub.historyRequests).toEqual(["chat-b"]);
        expect(stub.sent).toEqual([]);
    });
});
