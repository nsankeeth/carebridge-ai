import { TaskList } from "@/components/task-list";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function ClinicianTasksPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Follow-ups</CardTitle>
        <CardDescription>Administrative reminders for cases shared with you. Acknowledging or completing a review closes them automatically.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <TaskList endpoint="/clinician/tasks" queryKey="clinician-tasks" />
      </CardContent>
    </Card>
  );
}
