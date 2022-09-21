import asyncio
import io
import os
import random
import sys
import time
import unittest
import unittest.mock as mock
from contextlib import contextmanager
from functools import partial
from string import capwords
from unittest.mock import patch

import mlflow
import pytest
import wandb

import gradio as gr
from gradio.routes import PredictBody
from gradio.test_data.blocks_configs import XRAY_CONFIG
from gradio.utils import assert_configs_are_equivalent_besides_ids

pytest_plugins = ("pytest_asyncio",)

os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"


@contextmanager
def captured_output():
    new_out, new_err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class TestBlocks(unittest.TestCase):
    maxDiff = None

    def test_set_share(self):
        with gr.Blocks() as demo:
            # self.share is False when instantiating the class
            self.assertFalse(demo.share)
            # default is False, if share is None
            demo.share = None
            self.assertFalse(demo.share)
            # if set to True, it doesn't change
            demo.share = True
            self.assertTrue(demo.share)

    @patch("gradio.utils.colab_check")
    def test_set_share_in_colab(self, mock_colab_check):
        mock_colab_check.return_value = True
        with gr.Blocks() as demo:
            # self.share is False when instantiating the class
            self.assertFalse(demo.share)
            # default is True, if share is None and colab_check is true
            demo.share = None
            self.assertTrue(demo.share)
            # if set to True, it doesn't change
            demo.share = True
            self.assertTrue(demo.share)

    def test_xray(self):
        def fake_func():
            return "Hello There"

        xray_model = lambda diseases, img: {
            disease: random.random() for disease in diseases
        }
        ct_model = lambda diseases, img: {disease: 0.1 for disease in diseases}

        with gr.Blocks() as demo:
            gr.Markdown(
                """
            # Detect Disease From Scan
            With this model you can lorem ipsum
            - ipsum 1
            - ipsum 2
            """
            )
            disease = gr.CheckboxGroup(
                choices=["Covid", "Malaria", "Lung Cancer"], label="Disease to Scan For"
            )

            with gr.Tabs():
                with gr.TabItem("X-ray"):
                    with gr.Row():
                        xray_scan = gr.Image()
                        xray_results = gr.JSON()
                    xray_run = gr.Button("Run")
                    xray_run.click(
                        xray_model, inputs=[disease, xray_scan], outputs=xray_results
                    )

                with gr.TabItem("CT Scan"):
                    with gr.Row():
                        ct_scan = gr.Image()
                        ct_results = gr.JSON()
                    ct_run = gr.Button("Run")
                    ct_run.click(
                        ct_model, inputs=[disease, ct_scan], outputs=ct_results
                    )
            textbox = gr.Textbox()
            demo.load(fake_func, [], [textbox])

        config = demo.get_config_file()
        self.assertTrue(assert_configs_are_equivalent_besides_ids(XRAY_CONFIG, config))
        assert config["show_api"] is True
        _ = demo.launch(prevent_thread_lock=True, show_api=False)
        assert demo.config["show_api"] is False

    def test_load_from_config(self):
        def update(name):
            return f"Welcome to Gradio, {name}!"

        with gr.Blocks() as demo1:
            inp = gr.Textbox(placeholder="What is your name?")
            out = gr.Textbox()

            inp.submit(fn=update, inputs=inp, outputs=out, api_name="greet")

            gr.Image().style(height=54, width=240)

        config1 = demo1.get_config_file()
        demo2 = gr.Blocks.from_config(config1, [update])
        config2 = demo2.get_config_file()
        self.assertTrue(assert_configs_are_equivalent_besides_ids(config1, config2))

    def test_partial_fn_in_config(self):
        def greet(name, formatter):
            return formatter("Hello " + name + "!")

        greet_upper_case = partial(greet, formatter=capwords)
        with gr.Blocks() as demo:
            t = gr.Textbox()
            o = gr.Textbox()
            t.change(greet_upper_case, t, o)

        assert len(demo.fns) == 1
        assert "fn" in str(demo.fns[0])

    @pytest.mark.asyncio
    async def test_async_function(self):
        async def wait():
            await asyncio.sleep(0.01)
            return True

        with gr.Blocks() as demo:
            text = gr.Textbox()
            button = gr.Button()
            button.click(wait, [text], [text])

            body = PredictBody(data=1, fn_index=0)
            start = time.time()
            result = await demo.process_api(body)
            end = time.time()
            difference = end - start
            assert difference >= 0.01
            assert result

    def test_integration_wandb(self):
        with captured_output() as (out, err):
            wandb.log = mock.MagicMock()
            wandb.Html = mock.MagicMock()
            demo = gr.Blocks()
            with demo:
                gr.Textbox("Hi there!")
            demo.integrate(wandb=wandb)

            self.assertEqual(
                out.getvalue().strip(),
                "The WandB integration requires you to `launch(share=True)` first.",
            )
            demo.share_url = "tmp"
            demo.integrate(wandb=wandb)
            wandb.log.assert_called_once()

    @mock.patch("comet_ml.Experiment")
    def test_integration_comet(self, mock_experiment):
        experiment = mock_experiment()
        experiment.log_text = mock.MagicMock()
        experiment.log_other = mock.MagicMock()

        demo = gr.Blocks()
        with demo:
            gr.Textbox("Hi there!")

        demo.launch(prevent_thread_lock=True)
        demo.integrate(comet_ml=experiment)
        experiment.log_text.assert_called_with("gradio: " + demo.local_url)
        demo.share_url = "tmp"  # used to avoid creating real share links.
        demo.integrate(comet_ml=experiment)
        experiment.log_text.assert_called_with("gradio: " + demo.share_url)
        self.assertEqual(experiment.log_other.call_count, 2)
        demo.share_url = None
        demo.close()

    def test_integration_mlflow(self):
        mlflow.log_param = mock.MagicMock()
        demo = gr.Blocks()
        with demo:
            gr.Textbox("Hi there!")

        demo.launch(prevent_thread_lock=True)
        demo.integrate(mlflow=mlflow)
        mlflow.log_param.assert_called_with(
            "Gradio Interface Local Link", demo.local_url
        )
        demo.share_url = "tmp"  # used to avoid creating real share links.
        demo.integrate(mlflow=mlflow)
        mlflow.log_param.assert_called_with(
            "Gradio Interface Share Link", demo.share_url
        )
        demo.share_url = None
        demo.close()

    @mock.patch("requests.post")
    def test_initiated_analytics(self, mock_post):
        with gr.Blocks(analytics_enabled=True):
            pass
        mock_post.assert_called_once()


class TestComponentsInBlocks:
    def test_slider_random_value_config(self):
        with gr.Blocks() as demo:
            gr.Slider(
                value=11.2,
                minimum=-10.2,
                maximum=15,
                label="Non-random Slider (Static)",
            )
            gr.Slider(
                randomize=True,
                minimum=100,
                maximum=200,
                label="Random Slider (Input 1)",
            )
            gr.Slider(
                randomize=True,
                minimum=10,
                maximum=23.2,
                label="Random Slider (Input 2)",
            )
        for component in demo.blocks.values():
            if isinstance(component, gr.components.IOComponent):
                if "Non-random" in component.label:
                    assert not component.attach_load_event
                else:
                    assert component.attach_load_event
        dependencies_on_load = [
            dep["trigger"] == "load" for dep in demo.config["dependencies"]
        ]
        assert all(dependencies_on_load)
        assert len(dependencies_on_load) == 2
        assert not any([dep["queue"] for dep in demo.config["dependencies"]])

    def test_io_components_attach_load_events_when_value_is_fn(self, io_components):
        io_components = [comp for comp in io_components if not (comp == gr.State)]
        interface = gr.Interface(
            lambda *args: None,
            inputs=[comp(value=lambda: None) for comp in io_components],
            outputs=None,
        )

        dependencies_on_load = [
            dep for dep in interface.config["dependencies"] if dep["trigger"] == "load"
        ]
        assert len(dependencies_on_load) == len(io_components)

    def test_blocks_do_not_filter_none_values_from_updates(self, io_components):
        io_components = [c() for c in io_components if c not in [gr.State, gr.Button]]
        with gr.Blocks() as demo:
            for component in io_components:
                component.render()
            btn = gr.Button(value="Reset")
            btn.click(
                lambda: [gr.update(value=None) for _ in io_components],
                inputs=[],
                outputs=io_components,
            )

        output = demo.postprocess_data(
            0, [gr.update(value=None) for _ in io_components], state=None
        )
        assert all(
            [o["value"] == c.postprocess(None) for o, c in zip(output, io_components)]
        )

    def test_blocks_does_not_replace_keyword_literal(self):
        with gr.Blocks() as demo:
            text = gr.Textbox()
            btn = gr.Button(value="Reset")
            btn.click(
                lambda: gr.update(value="NO_VALUE"),
                inputs=[],
                outputs=text,
            )

        output = demo.postprocess_data(0, gr.update(value="NO_VALUE"), state=None)
        assert output[0]["value"] == "NO_VALUE"


def test_blocks_returns_correct_output_dict_single_key():

    with gr.Blocks() as demo:
        num = gr.Number()
        num2 = gr.Number()
        update = gr.Button(value="update")

        def update_values():
            return {num2: gr.Number.update(value=42)}

        update.click(update_values, inputs=[num], outputs=[num2])

    output = demo.postprocess_data(0, {num2: gr.Number.update(value=42)}, state=None)
    assert output[0]["value"] == 42

    output = demo.postprocess_data(0, {num2: 23}, state=None)
    assert output[0] == 23


class TestCallFunction:
    @pytest.mark.asyncio
    async def test_call_regular_function(self):
        with gr.Blocks() as demo:
            text = gr.Textbox()
            btn = gr.Button()
            btn.click(
                lambda x: "Hello, " + x,
                inputs=text,
                outputs=text,
            )

        output = await demo.call_function(0, ["World"])
        assert output["prediction"] == "Hello, World"
        output = await demo.call_function(0, ["Abubakar"])
        assert output["prediction"] == "Hello, Abubakar"

    @pytest.mark.asyncio
    async def test_call_generator(self):
        def generator(x):
            for i in range(x):
                yield i

        with gr.Blocks() as demo:
            inp = gr.Number()
            out = gr.Number()
            btn = gr.Button()
            btn.click(
                generator,
                inputs=inp,
                outputs=out,
            )

        demo.queue()
        assert demo.config["enable_queue"]

        output = await demo.call_function(0, [3])
        assert output["prediction"] == 0
        output = await demo.call_function(0, [3], iterator=output["iterator"])
        assert output["prediction"] == 1
        output = await demo.call_function(0, [3], iterator=output["iterator"])
        assert output["prediction"] == 2
        output = await demo.call_function(0, [3], iterator=output["iterator"])
        assert output["prediction"] == gr.components._Keywords.FINISHED_ITERATING
        assert output["iterator"] is None
        output = await demo.call_function(0, [3], iterator=output["iterator"])
        assert output["prediction"] == 0

    @pytest.mark.asyncio
    async def test_call_both_generator_and_function(self):
        def generator(x):
            for i in range(x):
                yield i, x

        with gr.Blocks() as demo:
            inp = gr.Number()
            out1 = gr.Number()
            out2 = gr.Number()
            btn = gr.Button()
            inp.change(lambda x: x + x, inp, out1)
            btn.click(
                generator,
                inputs=inp,
                outputs=[out1, out2],
            )

        demo.queue()

        output = await demo.call_function(0, [2])
        assert output["prediction"] == 4
        output = await demo.call_function(0, [-1])
        assert output["prediction"] == -2

        output = await demo.call_function(1, [3])
        assert output["prediction"] == (0, 3)
        output = await demo.call_function(1, [3], iterator=output["iterator"])
        assert output["prediction"] == (1, 3)
        output = await demo.call_function(1, [3], iterator=output["iterator"])
        assert output["prediction"] == (2, 3)
        output = await demo.call_function(1, [3], iterator=output["iterator"])
        assert output["prediction"] == (gr.components._Keywords.FINISHED_ITERATING,) * 2
        assert output["iterator"] is None
        output = await demo.call_function(1, [3], iterator=output["iterator"])
        assert output["prediction"] == (0, 3)


class TestSpecificUpdate:
    def test_without_update(self):
        with pytest.raises(KeyError):
            gr.Textbox.get_specific_update({"lines": 4})

    def test_with_update(self):
        specific_update = gr.Textbox.get_specific_update(
            {"lines": 4, "__type__": "update"}
        )
        assert specific_update == {
            "lines": 4,
            "max_lines": None,
            "placeholder": None,
            "label": None,
            "show_label": None,
            "visible": None,
            "value": gr.components._Keywords.NO_VALUE,
            "__type__": "update",
        }

    def test_with_generic_update(self):
        specific_update = gr.Video.get_specific_update(
            {"visible": True, "value": "test.mp4", "__type__": "generic_update"}
        )
        assert specific_update == {
            "source": None,
            "label": None,
            "show_label": None,
            "interactive": None,
            "visible": True,
            "value": "test.mp4",
            "__type__": "update",
        }


if __name__ == "__main__":
    unittest.main()
