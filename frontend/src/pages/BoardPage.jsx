import { Badge, Card, Group, Paper, SimpleGrid, Stack, Text, Tooltip } from "@mantine/core";
import { IconMicrophone } from "@tabler/icons-react";
import { useState } from "react";
import { api } from "../api.js";
import { useMe } from "../context.jsx";
import { Banner, Page, UserAvatar } from "../components/ui.jsx";
import TaskModal from "../components/TaskModal.jsx";
import { parseDate, TASK_STATUS } from "../format.js";
import { useLoad } from "../hooks.js";
import { canEditTask } from "../permissions.js";
import { TASK_STATUS_COLOR } from "../theme.js";

const DAY = 24 * 3600 * 1000;

export default function BoardPage() {
  const { me, can, byId } = useMe();
  const { data: tasks, error, reload } = useLoad(api.tasks, []);
  const [open, setOpen] = useState(null);
  const [over, setOver] = useState(null);
  const [moveError, setMoveError] = useState(null);

  const move = async (taskId, status) => {
    setOver(null);
    const task = tasks.find((t) => t.id === taskId);
    if (!task || task.status === status) return;
    try {
      await api.updateTask(taskId, { status });
      setMoveError(null);
    } catch (e) {
      setMoveError(e.message);
    }
    reload(true);
  };

  return (
    <Page title="Доска" sub="Перетащите карточку в другую колонку или откройте её">
      {error ? <Banner kind="error">{error.message}</Banner> : null}
      {moveError ? <Banner kind="error">{moveError}</Banner> : null}
      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
        {Object.entries(TASK_STATUS).map(([status, label]) => {
          const items = (tasks ?? []).filter((t) => t.status === status);
          return (
            <Paper
              key={status}
              p="sm"
              className="board-col"
              data-over={over === status || undefined}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(status);
              }}
              onDragLeave={() => setOver((s) => (s === status ? null : s))}
              onDrop={(e) => {
                e.preventDefault();
                move(Number(e.dataTransfer.getData("text/plain")), status);
              }}
            >
              <Group justify="space-between" px={4} mb="sm">
                <Group gap={8}>
                  <Badge variant="dot" color={TASK_STATUS_COLOR[status]} size="lg" tt="none" fw={600}>{label}</Badge>
                </Group>
                <Text size="sm" c="dimmed" fw={500}>{items.length}</Text>
              </Group>
              <Stack gap="sm">
                {items.map((t) => {
                  const fresh = t.origin_meeting_id && Date.now() - parseDate(t.created_at) < DAY;
                  const draggable = canEditTask(me, can, t);
                  return (
                    <Card
                      key={t.id}
                      p="md"
                      radius="md"
                      className="issue"
                      data-fresh={fresh || undefined}
                      data-locked={!draggable || undefined}
                      draggable={draggable}
                      tabIndex={0}
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(t.id))}
                      onClick={() => setOpen(t.id)}
                      onKeyDown={(e) => e.key === "Enter" && setOpen(t.id)}
                    >
                      <Text size="xs" c="dimmed" ff="monospace">{t.key}</Text>
                      <Text size="sm" fw={500} mt={4} lineClamp={3}>{t.title}</Text>
                      <Group justify="space-between" mt="sm">
                        {t.origin_meeting_id ? (
                          <Tooltip label={t.origin_meeting_title ? `Создано со встречи «${t.origin_meeting_title}»` : "Создано со встречи"} withArrow>
                            <Badge
                              variant="light"
                              size="sm"
                              tt="none"
                              maw={170}
                              leftSection={<IconMicrophone size={12} />}
                              data-testid="from-meeting"
                            >
                              Со встречи{t.origin_meeting_title ? ` · ${t.origin_meeting_title}` : ""}
                            </Badge>
                          </Tooltip>
                        ) : (
                          <span />
                        )}
                        <Group gap={6}>
                          {t.due_text ? <Text size="xs" c="dimmed">{t.due_text}</Text> : null}
                          {t.assignee_id ? <UserAvatar user={byId[t.assignee_id]} size="sm" /> : null}
                        </Group>
                      </Group>
                    </Card>
                  );
                })}
              </Stack>
            </Paper>
          );
        })}
      </SimpleGrid>
      {open ? <TaskModal taskId={open} onClose={() => setOpen(null)} onChanged={() => reload(true)} /> : null}
    </Page>
  );
}
