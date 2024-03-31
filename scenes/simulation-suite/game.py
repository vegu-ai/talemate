
def game(TM):
    
    MSG_PROCESSED_INSTRUCTIONS = "Simulation suite processed instructions"
    
    MSG_HELP = "Instructions to the simulation computer are only processed if the computer is directly addressed at the beginning of the instruction. Please state your commands by addressing the computer by stating \"Computer,\" followed by an instruction. For example ... \"Computer, i want to experience being on a derelict spaceship.\""
    
    PROMPT_NARRATE_ROUND = "Narrate the simulation and reveal some new details to the player in one paragraph. YOU MUST NOT ADDRESS THE COMPUTER OR THE SIMULATION."
    
    PROMPT_STARTUP = "Narrate the computer asking the user to state the nature of their desired simulation in a synthetic and soft sounding voice."
    
    CTX_PIN_UNAWARE = "Characters in the simulation ARE NOT AWARE OF THE COMPUTER."
    
    AUTO_NARRATE_INTERVAL = 10
    
    def parse_sim_call_arguments(call:str) -> str:
        """
        Returns the value between the parentheses of a simulation call
        
        Example:
        
        call = 'change_environment("a house")'
        
        parse_sim_call_arguments(call) -> "a house"
        """
        
        try:
            return call.split("(", 1)[1].split(")")[0]
        except Exception:
            return ""
    
    class SimulationSuite:
        
        def __init__(self):
            # do we update the world state at the end of the round
            self.update_world_state = False
            
            self.simulation_reset = False
            
            self.added_npcs = []
            
            TM.log.debug("SIMULATION SUITE INIT...")
            
            self.player_character = TM.scene.get_player_character()
            self.player_message = TM.scene.last_player_message()
            self.last_processed_call = TM.game_state.get_var("instr.lastprocessed_call", -1)
            self.player_message_is_instruction = (
                self.player_message and
                self.player_message.raw.lower().startswith("computer") and
                not self.player_message.hidden and
                not self.last_processed_call > self.player_message.id
            )
            
        
        def run(self):
            if not TM.game_state.has_var("instr.simulation_stopped"):
                self.simulation()
            
            self.finalize_round()
            
        def simulation(self):
            
            if not TM.game_state.has_var("instr.simulation_started"):
                self.startup()
            else:
                self.simulation_calls()
                
            if self.update_world_state:
                self.run_update_world_state(force=True)
                
            
        def startup(self):
            TM.emit_status("busy", "Simulation suite powering up.", as_scene_message=True)
            TM.game_state.set_var("instr.simulation_started", "yes", commit=False)
            TM.agents.narrator.action_to_narration(
                action_name="progress_story",
                narrative_direction=PROMPT_STARTUP,
                emit_message=False
            )
            TM.agents.narrator.action_to_narration(
                action_name="passthrough",
                narration=MSG_HELP
            )
            TM.agents.world_state.manager(
                action_name="save_world_entry",
                entry_id="sim.quarantined",
                text=CTX_PIN_UNAWARE,
                meta={},
                pin=True
            )
            TM.game_state.set_var("instr.simulation_started", "yes", commit=False)
            TM.emit_status("success", "Simulation suite ready", as_scene_message=True)
            self.update_world_state = True
            
        def simulation_calls(self):
            """
            Calls the simulation suite main prompt to determine the appropriate
            simulation calls
            """
            
            if not self.player_message_is_instruction or self.player_message.id == self.last_processed_call:
                return
            
            # First instruction?
            if not TM.game_state.has_var("instr.has_issued_instructions"):
                
                # determine the context of the simulation
                
                context_context = TM.agents.creator.determine_content_context_for_description(
                    description=self.player_message.raw,
                )
                TM.scene.set_content_context(context_context)
            

            calls = TM.client.render_and_request(
                "computer",
                dedupe_enabled=False,
                player_instruction=self.player_message.raw,
                scene=TM.scene,
            )
            
            self.calls = calls = calls.split("\n")
            
            calls = self.prepare_calls(calls)
            
            TM.log.debug("SIMULATION SUITE CALLS", callse=calls)
            
            # calls that are processed
            processed = []
            
            for call in calls:
                processed_call = self.process_call(call)
                if processed_call:
                    processed.append(processed_call)
            
            """
            {% set _ = emit_status("busy", "Simulation suite altering environment.", as_scene_message=True) %}
            {% set update_world_state = True %}
            {% set _ = agent_action("narrator", "action_to_narration", action_name="progress_story", narrative_direction="The computer calls the following functions:\n"+processed.join("\n")+"\nand the simulation adjusts the environment according to the user's wishes.\n\nWrite the narrative that describes the changes to the player in the context of the simulation starting up.", emit_message=True) %}
            """
            
            if processed:
                TM.log.debug("SIMULATION SUITE CALLS", calls=processed)
                TM.game_state.set_var("instr.has_issued_instructions", "yes", commit=False)
            
            TM.emit_status("busy", "Simulation suite altering environment.", as_scene_message=True)
            compiled = "\n".join(processed)
            if not self.simulation_reset and compiled:
                TM.agents.narrator.action_to_narration(
                    action_name="progress_story",
                    narrative_direction=f"The computer calls the following functions:\n\n{compiled}\n\nand the simulation adjusts the environment according to the user's wishes.\n\nWrite the narrative that describes the changes to the player in the context of the simulation starting up. YOU MUST NOT REFERENCE THE COMPUTER.",
                    emit_message=True
                )
                
            self.update_world_state = True
            
            self.set_simulation_title(compiled)
            
        def set_simulation_title(self, compiled_calls):
            
            """
            Generates a fitting title for the simulation based on the user's instructions
            """
            
            TM.log.debug("SIMULATION SUITE: set simulation title", name=TM.scene.title, compiled_calls=compiled_calls)
            
            if not compiled_calls:
                return
            
            if TM.scene.title != "Simulation Suite":
                # name already changed, no need to do it again
                return
            
            title = TM.agents.creator.contextual_generate_from_args(
                "scene:simulation title",
                "Create a fitting title for the simulated scenario that the user has requested. You response MUST be a short but exciting, descriptive title.",
                length=75                
            )
            
            title = title.strip('"').strip()
            
            TM.scene.set_title(title)
            
        def prepare_calls(self, calls):
            """
            Loops through calls and if a `set_player_name` call and a `set_player_persona` call are both
            found, ensure that the `set_player_name` call is processed first by moving it in front of the
            `set_player_persona` call.
            """
            
            set_player_name_call_exists = -1
            set_player_persona_call_exists = -1
            
            i = 0
            for call in calls:
                if "set_player_name" in call:
                    set_player_name_call_exists = i
                elif "set_player_persona" in call:
                    set_player_persona_call_exists = i
                i = i + 1
                    
            if set_player_name_call_exists > -1 and set_player_persona_call_exists > -1:

                if set_player_name_call_exists > set_player_persona_call_exists:
                    calls.insert(set_player_persona_call_exists, calls.pop(set_player_name_call_exists))
                    TM.log.debug("SIMULATION SUITE: prepare calls - moved set_player_persona call", calls=calls)
                    
            return calls
            
        def process_call(self, call:str) -> str:
            """
            Processes a simulation call
            
            Simulation alls are pseudo functions that are called by the simulation suite
            
            We grab the function name by splitting against ( and taking the first element
            if the SimulationSuite has a method with the name _call_{function_name} then we call it
            
            if a function name could be found but we do not have a method to call we dont do anything
            but we still return it as procssed as the AI can still interpret it as something later on
            """
            
            if "(" not in call:
                return None
            
            function_name = call.split("(")[0]
            
            if hasattr(self, f"call_{function_name}"):
                TM.log.debug("SIMULATION SUITE CALL", call=call, function_name=function_name)
                
                inject = f"The computer executes the function `{call}`"
                
                return getattr(self, f"call_{function_name}")(call, inject)
            
            return call
        
        
        def call_set_simulation_goal(self, call:str, inject:str) -> str:
            """
            Set's the simulation goal as a permanent pin
            """
            TM.emit_status("busy", "Simulation suite setting goal.", as_scene_message=True)
            TM.agents.world_state.manager(
                action_name="save_world_entry",
                entry_id="sim.goal",
                text=self.player_message.raw,
                meta={},
                pin=True
            )
            
            TM.agents.director.log_action(
                action=parse_sim_call_arguments(call),
                action_description="The computer sets the goal for the simulation.",
            )
            
            return call
        
        def call_change_environment(self, call:str, inject:str) -> str:
            """
            Simulation changes the environment, this is entirely interpreted by the AI
            and we dont need to do any logic on our end, so we just return the call
            """
            
            TM.agents.director.log_action(
                action=parse_sim_call_arguments(call),
                action_description="The computer changes the environment of the simulation."
            )
            
            return call
        
        
        def call_answer_question(self, call:str, inject:str) -> str:
            """
            The player asked the simulation a query, we need to process this and have
            the AI produce an answer
            """
            
            TM.agents.narrator.action_to_narration(
                action_name="progress_story",
                narrative_direction=f"The computer calls the following function:\n\n{call}\n\nand answers the player's question.",
                emit_message=True
            )
        
        
        def call_set_player_persona(self, call:str, inject:str) -> str:
            
            """
            The simulation suite is altering the player persona
            """
            
            TM.emit_status("busy", "Simulation suite altering user persona.", as_scene_message=True)
            character_attributes = TM.agents.world_state.extract_character_sheet(
                name=self.player_character.name, text=inject, alteration_instructions=self.player_message.raw
            )
            self.player_character.update(base_attributes=character_attributes)
            
            character_description = TM.agents.creator.determine_character_description(character=self.player_character)
            self.player_character.update(description=character_description)
            TM.log.debug("SIMULATION SUITE: transform player", attributes=character_attributes, description=character_description)
            
            TM.agents.director.log_action(
                action=parse_sim_call_arguments(call),
                action_description="The computer transforms the player persona."
            )
            
            return call


        def call_set_player_name(self, call:str, inject:str) -> str:
            
            """
            The simulation suite is altering the player name
            """
            
            TM.emit_status("busy", "Simulation suite adjusting user identity.", as_scene_message=True)
            character_name = TM.agents.creator.determine_character_name(character_name=f"{inject} - What is a fitting name for the player persona? Respond with the current name if it still fits.")
            TM.log.debug("SIMULATION SUITE: player name", character_name=character_name)
            if character_name != self.player_character.name:
                self.player_character.rename(character_name)
                
            TM.agents.director.log_action(
                action=parse_sim_call_arguments(call),
                action_description=f"The computer changes the player's identity to {character_name}."
            )
                
            return call


        def call_add_ai_character(self, call:str, inject:str) -> str:
            
            # sometimes the AI will call this function an pass an inanimate object as the parameter
            # we need to determine if this is the case and just ignore it
            is_inanimate = TM.client.query_text_eval("does the function add an inanimate object?", call)
            
            if is_inanimate:
                TM.log.debug("SIMULATION SUITE: add npc - inanimate object", call=call)
                return
            
            # sometimes the AI will ask if the function adds a group of characters, we need to
            # determine if this is the case
            adds_group = TM.client.query_text_eval("does the function add a group of characters?", call)
            
            TM.log.debug("SIMULATION SUITE: add npc", adds_group=adds_group)
            
            TM.emit_status("busy", "Simulation suite adding character.", as_scene_message=True)
            
            if not adds_group:
                character_name = TM.agents.creator.determine_character_name(character_name=f"{inject} - what is the name of the character to be added to the scene? If no name can extracted from the text, extract a short descriptive name instead. Respond only with the name.")
            else:
                character_name = TM.agents.creator.determine_character_name(character_name=f"{inject} - what is the name of the group of characters to be added to the scene? If no name can extracted from the text, extract a short descriptive name instead. Respond only with the name.", group=True)
            
            # sometimes add_ai_character and change_ai_character are called in the same instruction targeting
            # the same character, if this happens we need to combine into a single add_ai_character call
            
            has_change_ai_character_call = TM.client.query_text_eval(f"Are there any calls to `change_ai_character` in the instruction for {character_name}?", "\n".join(self.calls))
            
            if has_change_ai_character_call:
                combined_arg = TM.agents.world_state.analyze_and_follow_instruction(
                    "\n".join(self.calls),
                    f"Combine the arguments of the function calls `add_ai_character` and `change_ai_character` for {character_name} into a single text string. Respond with the new argument."
                )
                call = f"add_ai_character({combined_arg})"
                inject = f"The computer executes the function `{call}`"
                
            
            TM.emit_status("busy", f"Simulation suite adding character: {character_name}", as_scene_message=True)
            
            TM.log.debug("SIMULATION SUITE: add npc", name=character_name)
            
            npc = TM.agents.director.persist_character(name=character_name, content=self.player_message.raw+f"\n\n{inject}", determine_name=False)
            
            self.added_npcs.append(npc.name)
            
            TM.agents.world_state.manager(
                action_name="add_detail_reinforcement",
                character_name=npc.name,
                question="Goal",
                instructions=f"Generate a goal for {npc.name}, based on the user's chosen simulation",
                interval=25,
                run_immediately=True
            )
            
            TM.log.debug("SIMULATION SUITE: added npc", npc=npc)
            
            TM.agents.visual.generate_character_portrait(character_name=npc.name)
            
            TM.agents.director.log_action(
                action=parse_sim_call_arguments(call),
                action_description=f"The computer adds {npc.name} to the simulation."
            )
            
            return call        


        def call_remove_ai_character(self, call:str, inject:str) -> str:
            TM.emit_status("busy", "Simulation suite removing character.", as_scene_message=True)
            
            character_name = TM.agents.creator.determine_character_name(character_name=f"{inject} - what is the name of the character being removed?", allowed_names=TM.scene.npc_character_names())
            
            npc = TM.scene.get_character(character_name)
            
            if npc:
                TM.log.debug("SIMULATION SUITE: remove npc", npc=npc.name)
                TM.agents.world_state.manager(action_name="deactivate_character", character_name=npc.name)
                
                TM.agents.director.log_action(
                    action=parse_sim_call_arguments(call),
                    action_description=f"The computer removes {npc.name} from the simulation."
                )
            
            return call

        def call_change_ai_character(self, call:str, inject:str) -> str:
            TM.emit_status("busy", "Simulation suite altering character.", as_scene_message=True)
            
            character_name = TM.agents.creator.determine_character_name(character_name=f"{inject} - what is the name of the character receiving the changes (before the change)?", allowed_names=TM.scene.npc_character_names())
            
            if character_name in self.added_npcs:
                # we dont want to change the character if it was just added
                return
            
            character_name_after = TM.agents.creator.determine_character_name(character_name=f"{inject} - what is the name of the character receiving the changes (after the changes)?")
            
            npc = TM.scene.get_character(character_name)
            
            if npc:
                TM.emit_status("busy", f"Changing {character_name} -> {character_name_after}", as_scene_message=True)
                
                TM.log.debug("SIMULATION SUITE: transform npc", npc=npc)
                
                character_attributes = TM.agents.world_state.extract_character_sheet(name=npc.name, alteration_instructions=self.player_message.raw)
                
                npc.update(base_attributes=character_attributes)
                character_description = TM.agents.creator.determine_character_description(character=npc)
                
                npc.update(description=character_description)
                TM.log.debug("SIMULATION SUITE: transform npc", attributes=character_attributes, description=character_description)
                
                if character_name_after != character_name:
                    npc.rename(character_name_after)
                    
                TM.agents.director.log_action(
                    action=parse_sim_call_arguments(call),
                    action_description=f"The computer transforms {npc.name}."
                )
                    
            return call
        
        def call_end_simulation(self, call:str, inject:str) -> str:
            
            explicit_command = TM.client.query_text_eval("has the player explicitly asked to end the simulation?", self.player_message.raw)
            
            if explicit_command:
                TM.emit_status("busy", "Simulation suite ending current simulation.", as_scene_message=True)
                TM.agents.narrator.action_to_narration(
                    action_name="progress_story",
                    narrative_direction=f"Narrate the computer ending the simulation, dissolving the environment and all artificial characters, erasing all memory of it and finally returning the player to the inactive simulation suite. List of artificial characters: {', '.join(TM.scene.npc_character_names())}. The player is also transformed back to their normal, non-descript persona as the form of {self.player_character.name} ceases to exist.",
                    emit_message=True
                )
                TM.scene.restore()

                self.simulation_reset = True
                
                TM.game_state.unset_var("instr.has_issued_instructions")
                TM.game_state.unset_var("instr.lastprocessed_call")
                TM.game_state.unset_var("instr.simulation_started")
                
                TM.agents.director.log_action(
                    action=parse_sim_call_arguments(call),
                    action_description="The computer ends the simulation."
                )
                
        def finalize_round(self):
            
            # track rounds
            rounds = TM.game_state.get_var("instr.rounds", 0)
            
            # increase rounds
            TM.game_state.set_var("instr.rounds", rounds + 1, commit=False)
            
            has_issued_instructions = TM.game_state.has_var("instr.has_issued_instructions")
            
            if self.update_world_state:
                self.run_update_world_state()
                
            if self.player_message_is_instruction:
                self.player_message.hide()
                TM.game_state.set_var("instr.lastprocessed_call", self.player_message.id, commit=False)
                TM.emit_status("success", MSG_PROCESSED_INSTRUCTIONS, as_scene_message=True)
                
            elif self.player_message and not has_issued_instructions:
                # simulation started, player message is NOT an instruction, and player has not given
                # any instructions
                self.guide_player()

            elif self.player_message and not TM.scene.npc_character_names():
                # simulation started, player message is NOT an instruction, but there are no npcs to interact with 
                self.narrate_round()
            
            elif rounds % AUTO_NARRATE_INTERVAL == 0 and rounds and TM.scene.npc_character_names() and has_issued_instructions:
                # every 3 rounds, narrate the round
                self.narrate_round()
         
        def guide_player(self):
            TM.agents.narrator.action_to_narration(
                action_name="paraphrase",
                narration=MSG_HELP,
                emit_message=True
            )
                
        def narrate_round(self):
            TM.agents.narrator.action_to_narration(
                action_name="progress_story",
                narrative_direction=PROMPT_NARRATE_ROUND,
                emit_message=True
            )
            
        def run_update_world_state(self, force=False):
            TM.log.debug("SIMULATION SUITE: update world state", force=force)
            TM.emit_status("busy", "Simulation suite updating world state.", as_scene_message=True)
            TM.agents.world_state.update_world_state(force=force)
            TM.emit_status("success", "Simulation suite updated world state.", as_scene_message=True)
            
    SimulationSuite().run()