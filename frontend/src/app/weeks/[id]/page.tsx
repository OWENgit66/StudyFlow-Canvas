import { WeekPage } from "@/components/week-page";
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WeekPage key={id} id={Number(id)} />;
}
