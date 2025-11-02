
from typing import Optional

from multi_agent_coding_system.agents.env_interaction.entities.conversation_history import ConversationHistory
from multi_agent_coding_system.agents.actions.orchestrator_hub import OrchestratorHub


class OrchestratorState:
    """Manages the complete state for the orchestrator."""
    
    def __init__(self, orchestrator_hub: OrchestratorHub, conversation_history: ConversationHistory):
        self.orchestrator_hub = orchestrator_hub
        self.conversation_history = conversation_history
        self.done = False
        self.finish_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert orchestrator state to dictionary format."""
        # Convert tasks to list of dicts
        tasks_list = []
        for _, task in self.orchestrator_hub.task_manager.tasks.items():
            tasks_list.append(task.to_dict())
        
        # Convert context store to list of dicts
        contexts_list = []
        for _, context in self.orchestrator_hub.context_store.items():
            contexts_list.append(context.to_dict())
        
        return {
            "done": self.done,
            "finish_message": self.finish_message,
            "tasks": tasks_list,
            "context_store": contexts_list,
            "conversation_history": self.conversation_history.to_dict()
        }
    
    def to_prompt(self) -> str:
        """Convert complete state to prompt format for LLM."""
        sections = []
        
        # Add task manager state
        sections.append("## Task Manager State\n")
        sections.append(self.orchestrator_hub.view_all_tasks())
        sections.append("\n## Context Store\n")
        sections.append(self.orchestrator_hub.view_context_store())
        
        # Add conversation history
        sections.append("\n## Conversation History\n")
        sections.append(self.conversation_history.to_prompt())
        
        return "\n".join(sections)
