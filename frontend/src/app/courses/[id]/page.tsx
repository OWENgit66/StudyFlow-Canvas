import { CoursePage } from "@/components/course-page";
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CoursePage key={id} id={Number(id)} />;
}
