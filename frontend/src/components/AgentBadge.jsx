import Chip from '@mui/material/Chip';
import SmartToyOutlined from '@mui/icons-material/SmartToyOutlined';

// Marks an AI agent account (users.is_agent from the API) wherever a user is
// shown, so an agent never passes for a person.
export default function AgentBadge(props) {
  return (
    <Chip
      icon={<SmartToyOutlined />}
      label="AI agent"
      size="small"
      color="secondary"
      variant="outlined"
      {...props}
    />
  );
}
