// CodeMirror 6 progressive enhancement for <textarea data-code-editor>.
// The textarea stays in the form (hidden) and is kept in sync, so the form
// submits normally and autosave sees changes.
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import {
  bracketMatching,
  HighlightStyle,
  indentOnInput,
  indentUnit,
  syntaxHighlighting,
} from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import {
  drawSelection,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { tags as t } from "@lezer/highlight";

const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.operatorKeyword, t.definitionKeyword, t.moduleKeyword], color: "var(--code-keyword)" },
  { tag: [t.string, t.special(t.string)], color: "var(--code-string)" },
  { tag: [t.number, t.bool, t.null], color: "var(--code-number)" },
  { tag: [t.comment, t.lineComment, t.blockComment], color: "var(--code-comment)", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.className], color: "var(--code-function)" },
  { tag: [t.standard(t.variableName), t.self], color: "var(--code-builtin)" },
]);

const theme = EditorView.theme({
  "&": {
    backgroundColor: "var(--code-bg)",
    color: "var(--code-fg)",
    fontSize: "0.86rem",
    borderRadius: "var(--radius-panel)",
    border: "1px solid var(--sf-border)",
    minHeight: "16rem",
  },
  "&.cm-focused": { outline: "2px solid var(--sf-ring)", outlineOffset: "2px" },
  ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.65" },
  ".cm-content": { padding: "0.85rem 0", caretColor: "var(--code-keyword)" },
  ".cm-gutters": {
    backgroundColor: "transparent",
    color: "var(--code-comment)",
    border: "none",
    paddingLeft: "0.5rem",
  },
  ".cm-activeLine": { backgroundColor: "var(--code-active-line)" },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--code-fg)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": {
    backgroundColor: "var(--code-selection) !important",
  },
  ".cm-cursor": { borderLeftColor: "var(--code-keyword)" },
  ".cm-matchingBracket": { backgroundColor: "rgb(226 194 125 / 0.18)", outline: "1px solid rgb(226 194 125 / 0.45)" },
});

function mount(textarea) {
  if (textarea.dataset.editorMounted) return;
  textarea.dataset.editorMounted = "true";
  const host = document.createElement("div");
  host.className = "sf-code-editor";
  textarea.after(host);
  textarea.hidden = true;
  const readOnly = textarea.hasAttribute("readonly");
  const view = new EditorView({
    parent: host,
    state: EditorState.create({
      doc: textarea.value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        history(),
        drawSelection(),
        indentOnInput(),
        bracketMatching(),
        highlightActiveLine(),
        indentUnit.of("    "),
        python(),
        syntaxHighlighting(highlight),
        keymap.of([indentWithTab, ...defaultKeymap, ...historyKeymap]),
        theme,
        EditorState.readOnly.of(readOnly),
        EditorView.contentAttributes.of({
          "aria-label": textarea.getAttribute("aria-label") || "Code editor",
          "aria-describedby": textarea.getAttribute("aria-describedby") || "",
        }),
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) return;
          textarea.value = update.state.doc.toString();
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
        }),
      ],
    }),
  });
  host.editorView = view;
}

window.SkillForgeEditor = {
  mountAll(root) {
    root.querySelectorAll("textarea[data-code-editor]").forEach(mount);
  },
};
window.SkillForgeEditor.mountAll(document);
