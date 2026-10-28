<script setup>
import { nextTick, onBeforeUnmount, ref } from "vue";

import { streamAgentMessage } from "./services/agent";

const starterPrompts = [
  "Find the top sushi places near 398371 Singapore",
  "Recommend hotpot restaurants near Tampines MRT",
  "Where can I find nasi lemak near Yishun MRT?",
  "Suggest ramen restaurants and libraries near Suntec City",
  "Find highly rated cafes near Singapore Changi Airport",
  "Recommend parks near Bishan MRT",
  "Find Thai restaurants near Bugis Junction",
  "Suggest museums near City Hall MRT",
  "Find halal restaurants near Geylang Serai",
  "Recommend coffee shops and bookstores near Orchard Road",
];

const suggestions = ref(selectStarterPrompts());
const messages = ref([]);
const draft = ref("");
const isSending = ref(false);
const chatScroll = ref(null);
const composer = ref(null);
const sessionId = ref(createSessionId());
let activeController = null;

function selectStarterPrompts() {
  const shuffled = [...starterPrompts];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[randomIndex]] = [
      shuffled[randomIndex],
      shuffled[index],
    ];
  }
  return shuffled.slice(0, 3);
}

function createSessionId() {
  return crypto.randomUUID().replaceAll("-", "");
}

function scrollToBottom() {
  nextTick(() => {
    chatScroll.value?.scrollTo({
      top: chatScroll.value.scrollHeight,
      behavior: "smooth",
    });
  });
}

function eventLabel(trace) {
  return trace.event.replaceAll("_", " ");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(
      /\[([^\]]+)]\((https:\/\/[^\s)]+)\)/g,
      (_, label, url) => {
        const normalizedUrl = url.replaceAll("\\&amp;", "&amp;");
        return `<a href="${normalizedUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      },
    )
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdown(value) {
  const blocks = [];
  let listType = null;
  let orderedItemCount = 0;

  const closeList = () => {
    if (listType) blocks.push(`</${listType}>`);
    listType = null;
  };

  for (const rawLine of value.split("\n")) {
    const line = rawLine.trim();
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    const orderedItem = line.match(/^\d+\.\s+(.+)$/);
    const unorderedItem = line.match(/^[-*]\s+(.+)$/);

    if (!line) {
      closeList();
    } else if (heading) {
      closeList();
      orderedItemCount = 0;
      blocks.push(`<h3>${renderInlineMarkdown(heading[1])}</h3>`);
    } else if (orderedItem || unorderedItem) {
      const nextListType = orderedItem ? "ol" : "ul";
      if (orderedItem) orderedItemCount += 1;
      if (listType !== nextListType) {
        closeList();
        listType = nextListType;
        blocks.push(
          listType === "ol"
            ? `<ol start="${orderedItemCount}">`
            : "<ul>",
        );
      }
      blocks.push(
        `<li>${renderInlineMarkdown((orderedItem || unorderedItem)[1])}</li>`,
      );
    } else {
      closeList();
      blocks.push(`<p>${renderInlineMarkdown(line)}</p>`);
    }
  }

  closeList();
  return blocks.join("");
}

function isVisibleTrace(event) {
  return new Set([
    "agent_thinking",
    "tool_call",
    "tool_output",
    "agent_output",
    "agent_completed",
    "agent_error",
  ]).has(event);
}

function resizeComposer(event) {
  const textarea = event.target;
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
}

function useSuggestion(suggestion) {
  draft.value = suggestion;
  nextTick(() => composer.value?.focus());
}

function newChat() {
  activeController?.abort();
  activeController = null;
  sessionId.value = createSessionId();
  messages.value = [];
  suggestions.value = selectStarterPrompts();
  draft.value = "";
  isSending.value = false;
  nextTick(() => composer.value?.focus());
}

async function sendMessage() {
  const text = draft.value.trim();
  if (!text || isSending.value) return;

  const requestSession = sessionId.value;
  const assistantMessage = {
    id: crypto.randomUUID(),
    role: "assistant",
    text: "",
    status: "streaming",
    traces: [],
  };

  messages.value.push({
    id: crypto.randomUUID(),
    role: "user",
    text,
  });
  messages.value.push(assistantMessage);
  draft.value = "";
  isSending.value = true;
  if (composer.value) composer.value.style.height = "auto";
  scrollToBottom();

  activeController = new AbortController();
  try {
    await streamAgentMessage({
      message: text,
      sessionId: requestSession,
      signal: activeController.signal,
      onEvent: ({ event, data }) => {
        if (requestSession !== sessionId.value) return;
        if (isVisibleTrace(event)) {
          assistantMessage.traces.push({
            id: crypto.randomUUID(),
            event,
            data,
          });
        }

        if (event === "agent_completed") {
          assistantMessage.text = data.output?.answer || "No answer was returned.";
          assistantMessage.status = "complete";
        } else if (event === "agent_error") {
          assistantMessage.text = data.detail || "The agent could not complete the request.";
          assistantMessage.status = "error";
        }
        scrollToBottom();
      },
    });

    if (assistantMessage.status === "streaming") {
      assistantMessage.status = "error";
      assistantMessage.text = "The response stream ended before an answer arrived.";
    }
  } catch (error) {
    if (error.name !== "AbortError" && requestSession === sessionId.value) {
      assistantMessage.status = "error";
      assistantMessage.text = error.message || "Unable to reach the agent.";
    }
  } finally {
    if (requestSession === sessionId.value) {
      isSending.value = false;
      activeController = null;
      scrollToBottom();
      nextTick(() => composer.value?.focus());
    }
  }
}

function handleComposerKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}

onBeforeUnmount(() => activeController?.abort());
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="#" aria-label="AskAround home" @click.prevent="newChat">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" role="img">
            <path d="M12 21s6-5.4 6-11a6 6 0 1 0-12 0c0 5.6 6 11 6 11Z" />
            <circle cx="12" cy="10" r="2.25" />
          </svg>
        </span>
        <span>AskAround</span>
      </a>

      <button class="new-chat-button" type="button" @click="newChat">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New chat
      </button>
    </header>

    <main ref="chatScroll" class="chat-scroll" aria-live="polite">
      <section v-if="messages.length === 0" class="empty-state">
        <div class="empty-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="M12 21s6-5.4 6-11a6 6 0 1 0-12 0c0 5.6 6 11 6 11Z" />
            <circle cx="12" cy="10" r="2.25" />
          </svg>
        </div>
        <p class="eyebrow">Your place discovery companion</p>
        <h1>Where should we go?</h1>
        <p class="empty-copy">
          Ask about places, plans, or what makes a destination worth visiting.
        </p>
        <div class="suggestions" aria-label="Suggested questions">
          <button
            v-for="suggestion in suggestions"
            :key="suggestion"
            type="button"
            @click="useSuggestion(suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>
      </section>

      <section v-else class="conversation" aria-label="Conversation">
        <article
          v-for="message in messages"
          :key="message.id"
          class="message"
          :class="`message-${message.role}`"
        >
          <div v-if="message.role === 'assistant'" class="assistant-avatar" aria-hidden="true">
            A
          </div>

          <div class="message-content">
            <p v-if="message.role === 'user'" class="user-bubble">{{ message.text }}</p>

            <template v-else>
              <div class="assistant-heading">
                <span>AskAround</span>
                <span v-if="message.status === 'streaming'" class="thinking-status">
                  <i></i> Working
                </span>
              </div>

              <div
                v-if="message.text"
                class="assistant-answer"
                :class="{ error: message.status === 'error' }"
                v-html="renderMarkdown(message.text)"
              ></div>
              <div v-else class="typing-indicator" aria-label="Agent is working">
                <span></span><span></span><span></span>
              </div>

              <details v-if="message.traces.length" class="trace-panel">
                <summary>
                  <span>Execution trace</span>
                  <span class="trace-count">{{ message.traces.length }} events</span>
                  <svg viewBox="0 0 20 20" aria-hidden="true">
                    <path d="m6 8 4 4 4-4" />
                  </svg>
                </summary>
                <div class="trace-list">
                  <div v-for="trace in message.traces" :key="trace.id" class="trace-event">
                    <div class="trace-event-heading">
                      <span class="trace-dot"></span>
                      <span>{{ eventLabel(trace) }}</span>
                    </div>
                    <pre>{{ JSON.stringify(trace.data, null, 2) }}</pre>
                  </div>
                </div>
              </details>
            </template>
          </div>
        </article>
      </section>
    </main>

    <footer class="composer-wrap">
      <form class="composer" @submit.prevent="sendMessage">
        <textarea
          ref="composer"
          v-model="draft"
          rows="1"
          maxlength="10000"
          placeholder="Ask AskAround…"
          aria-label="Message AskAround"
          :disabled="isSending"
          @input="resizeComposer"
          @keydown="handleComposerKeydown"
        ></textarea>
        <button
          class="send-button"
          type="submit"
          aria-label="Send message"
          :disabled="!draft.trim() || isSending"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m5 12 14-7-5 14-2.4-5.2L5 12Z" />
          </svg>
        </button>
      </form>
      <p>AskAround can make mistakes. Check important place details.</p>
    </footer>
  </div>
</template>
