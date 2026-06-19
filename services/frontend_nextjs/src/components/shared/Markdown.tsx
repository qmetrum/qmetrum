"use client";

import ReactMarkdown from "react-markdown";

/**
 * Theme-styled markdown renderer for AI agent output.
 *
 * react-markdown is safe by default — it does NOT render raw HTML (no rehype-raw),
 * so LLM output can't inject markup. We only style the standard block/inline
 * elements to match the app's typography.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div
      className={
        "text-sm leading-relaxed text-[var(--text-primary)] space-y-2 " +
        "[&_p]:my-0 " +
        "[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-0.5 " +
        "[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:space-y-0.5 " +
        "[&_li]:marker:text-[var(--text-muted)] " +
        "[&_strong]:font-semibold [&_strong]:text-[var(--navy)] " +
        "[&_em]:italic " +
        "[&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-[var(--text-primary)] " +
        "[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-[var(--text-primary)] " +
        "[&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-[var(--text-secondary)] " +
        "[&_code]:rounded [&_code]:bg-[var(--content-bg)] [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[12px] " +
        "[&_a]:text-[var(--teal)] [&_a]:underline [&_a]:underline-offset-2 " +
        "[&_blockquote]:border-l-2 [&_blockquote]:border-[var(--card-border)] [&_blockquote]:pl-3 [&_blockquote]:text-[var(--text-secondary)] " +
        "[&_table]:w-full [&_table]:text-xs [&_th]:text-left [&_th]:font-semibold [&_th]:py-1 [&_td]:py-1 [&_td]:border-t [&_td]:border-[var(--card-border)]"
      }
    >
      <ReactMarkdown
        components={{
          // open links safely in a new tab
          a: ({ ...props }) => <a target="_blank" rel="noopener noreferrer" {...props} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
