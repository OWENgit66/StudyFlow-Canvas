import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CourseQA } from "@/components/course-qa";
import { api } from "@/lib/api";

beforeEach(() => {
  vi.spyOn(api, 'indexStatus').mockResolvedValue({state:'ready', message:'Ready', total_chunks:1, indexed_chunks:1, missing_chunks:0});
});

const answer = { answerable: true, answer: "A grounded answer [1].", sources: [{
  citation_id: 1, resource_id: 3, title: "Link Layer.pdf", page: 17, week: "Week 2",
  resource_type: "lecture", source_url: "/api/resources/3/file#page=17",
}] };

describe("Course Q&A", () => {
  it.each(['indexing', 'stale', 'unavailable', 'error'] as const)('blocks Ask while index is %s and explains why', async (state) => {
    vi.mocked(api.indexStatus).mockResolvedValue({state, message: `Course index: ${state}`, total_chunks:1, indexed_chunks:0, missing_chunks:1});
    render(<CourseQA courseId={6} />);
    expect(await screen.findByText(`Course index: ${state}`)).toBeVisible();
    await userEvent.type(screen.getByLabelText('Ask your course'), 'Question');
    expect(screen.getByRole('button', {name:'Ask'})).toBeDisabled();
    expect(api.indexStatus).toHaveBeenCalledWith(6);
  });
  it("submits once, shows loading, renders answer and a real source link", async () => {
    let finish!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", fetch);
    render(<CourseQA courseId={2} />);
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Ask your course"), "CRC 是什么？");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(screen.getByRole("status")).toHaveTextContent("preparing your answer");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/courses/2/ask", expect.objectContaining({
      method: "POST", body: JSON.stringify({ question: "CRC 是什么？" }),
    }));
    await act(async () => finish(new Response(JSON.stringify(answer))));
    expect(await screen.findByText(answer.answer)).toBeVisible();
    const source = screen.getByRole("link", { name: "[1] Week 2 — Link Layer.pdf · Page 17" });
    expect(source).toHaveAttribute("href", "/api/resources/3/file#page=17");
    expect(source).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders a safe API error without server error details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"private traceback"}', { status: 503 })));
    render(<CourseQA courseId={2} />);
    await userEvent.type(screen.getByLabelText("Ask your course"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
    expect(document.body.textContent).not.toContain("traceback");
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
  });

  it("renders abstention without invented sources", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      answerable: false, answer: "当前课程材料中没有足够信息回答这个问题。", sources: [],
    }))));
    render(<CourseQA courseId={2} />);
    await userEvent.type(screen.getByLabelText("Ask your course"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("当前课程材料中没有足够信息回答这个问题。")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("does not turn unexpected source URLs or answer HTML into executable content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...answer,
      answer: '<script>alert("unsafe")</script>',
      sources: [{ ...answer.sources[0], source_url: 'javascript:alert(1)' }],
    }))));
    render(<CourseQA courseId={2} />);
    await userEvent.type(screen.getByLabelText("Ask your course"), "q");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText('<script>alert("unsafe")</script>')).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
