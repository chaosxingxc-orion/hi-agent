"""Unit tests for KnowledgeBuilder extracted from the central builder."""

import inspect
from unittest.mock import MagicMock, patch

from hi_agent.config.knowledge_builder import KnowledgeBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.knowledge.knowledge_manager import KnowledgeManager
from hi_agent.knowledge.user_knowledge import UserKnowledgeStore
from hi_agent.knowledge.wiki import KnowledgeWiki


def _config(tmp_path):
    return TraceConfig(episodic_storage_dir=str(tmp_path / "episodes"))


class TestKnowledgeBuilderInit:
    def test_init_with_config_only(self, tmp_path):
        config = _config(tmp_path)

        builder = KnowledgeBuilder(config)

        assert builder._config is config
        assert builder._long_term_graph_factory is None

    def test_init_with_factory(self, tmp_path):
        config = _config(tmp_path)
        factory = MagicMock()

        builder = KnowledgeBuilder(config, long_term_graph_factory=factory)

        assert builder._config is config
        assert builder._long_term_graph_factory is factory

    def test_knowledge_base_dir_derived_from_config(self, tmp_path):
        config = _config(tmp_path)
        builder = KnowledgeBuilder(config)

        assert builder._knowledge_base_dir() == config.episodic_storage_dir.replace("episodes", "")


class TestBuildKnowledgeWiki:
    def test_returns_knowledge_wiki_instance(self, tmp_path):
        builder = KnowledgeBuilder(_config(tmp_path))

        wiki = builder.build_knowledge_wiki()

        assert isinstance(wiki, KnowledgeWiki)

    def test_does_not_raise_on_missing_state(self, tmp_path):
        builder = KnowledgeBuilder(_config(tmp_path))

        with patch.object(KnowledgeWiki, "load", side_effect=FileNotFoundError):
            wiki = builder.build_knowledge_wiki()

        assert isinstance(wiki, KnowledgeWiki)


class TestBuildUserKnowledgeStore:
    def test_returns_user_knowledge_store_instance(self, tmp_path):
        builder = KnowledgeBuilder(_config(tmp_path))

        store = builder.build_user_knowledge_store()

        assert isinstance(store, UserKnowledgeStore)


class TestBuildKnowledgeManager:
    def test_returns_knowledge_manager_instance(self, tmp_path):
        graph = MagicMock()
        builder = KnowledgeBuilder(_config(tmp_path))

        manager = builder.build_knowledge_manager(long_term_graph=graph)

        assert isinstance(manager, KnowledgeManager)

    def test_accepts_pre_built_graph(self, tmp_path):
        graph = MagicMock()
        builder = KnowledgeBuilder(_config(tmp_path))

        manager = builder.build_knowledge_manager(long_term_graph=graph)

        assert manager.graph is graph

    def test_uses_factory_when_graph_not_provided(self, tmp_path):
        graph = MagicMock()
        factory = MagicMock(return_value=graph)
        builder = KnowledgeBuilder(_config(tmp_path), long_term_graph_factory=factory)

        manager = builder.build_knowledge_manager(profile_id="profile-a")

        factory.assert_called_once_with("profile-a")
        assert manager.graph is graph

    def test_skips_factory_when_graph_provided(self, tmp_path):
        graph = MagicMock()
        factory = MagicMock()
        builder = KnowledgeBuilder(_config(tmp_path), long_term_graph_factory=factory)

        manager = builder.build_knowledge_manager(
            profile_id="profile-a",
            long_term_graph=graph,
        )

        factory.assert_not_called()
        assert manager.graph is graph


class TestKnowledgeBuilderIsStandalone:
    def test_no_memory_builder_import(self):
        source = inspect.getsource(KnowledgeBuilder)

        assert "MemoryBuilder" not in source

    def test_no_system_builder_import(self):
        source = inspect.getsource(KnowledgeBuilder)

        assert "SystemBuilder" not in source
