"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>,
        table: ({ children, ...props }) => <div className="table-scroll"><table {...props}>{children}</table></div>,
      }}>{children}</ReactMarkdown>
    </div>
  );
}
